from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import (
    create_login_session,
    hash_password,
    hash_token,
    new_token,
    require_admin,
    set_session_cookie,
    utcnow,
)
from ..db import get_db
from ..models import Member, TeamRegistrationWindow
from ..schemas import (
    MemberOut,
    TeamRegistrationIn,
    TeamRegistrationInfo,
    TeamRegistrationWindowOpenOut,
    TeamRegistrationWindowOut,
)

router = APIRouter(prefix="/api/team-registration", tags=["team-registration"])

REGISTRATION_WINDOW_TTL = timedelta(hours=72)


def _registration_window(
    db: Session,
    token: str,
    *,
    lock: bool = False,
) -> TeamRegistrationWindow:
    query = select(TeamRegistrationWindow).where(
        TeamRegistrationWindow.token_hash == hash_token(token)
    )
    if lock:
        query = query.with_for_update()
    window = db.scalar(query)
    if window is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="注册链接无效")
    if window.closed_at is not None or window.expires_at <= utcnow():
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="本次团队注册已结束")
    return window


def _active_window_query():
    return (
        select(TeamRegistrationWindow)
        .where(
            TeamRegistrationWindow.closed_at.is_(None),
            TeamRegistrationWindow.expires_at > utcnow(),
        )
        .order_by(TeamRegistrationWindow.created_at.desc(), TeamRegistrationWindow.id.desc())
    )


@router.get("/admin/current", response_model=TeamRegistrationWindowOut | None)
def current_registration_window(
    _: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TeamRegistrationWindow | None:
    return db.scalar(_active_window_query())


@router.post(
    "/admin/open",
    response_model=TeamRegistrationWindowOpenOut,
    status_code=status.HTTP_201_CREATED,
)
def open_registration_window(
    current: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TeamRegistrationWindowOpenOut:
    if db.scalar(_active_window_query().with_for_update()) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="团队注册已经开放")

    token = new_token()
    window = TeamRegistrationWindow(
        token_hash=hash_token(token),
        expires_at=utcnow() + REGISTRATION_WINDOW_TTL,
        created_by=current.id,
    )
    db.add(window)
    db.commit()
    db.refresh(window)
    return TeamRegistrationWindowOpenOut(
        id=window.id,
        expires_at=window.expires_at,
        created_at=window.created_at,
        register_path=f"/register/{token}",
    )


@router.post("/admin/close", status_code=status.HTTP_204_NO_CONTENT)
def close_registration_window(
    _: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    window = db.scalar(_active_window_query().with_for_update())
    if window is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="团队注册当前未开放")
    window.closed_at = utcnow()
    db.commit()


@router.get("/{token}", response_model=TeamRegistrationInfo)
def registration_info(token: str, db: Session = Depends(get_db)) -> TeamRegistrationInfo:
    window = _registration_window(db, token)
    return TeamRegistrationInfo(expires_at=window.expires_at)


@router.post("/{token}/register", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def register_member(
    token: str,
    payload: TeamRegistrationIn,
    response: Response,
    db: Session = Depends(get_db),
) -> Member:
    _registration_window(db, token, lock=True)

    if db.scalar(select(Member.id).where(Member.email == payload.email)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已注册，请直接登录。")
    if db.scalar(select(Member.id).where(Member.student_id == payload.student_id)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该学号已被使用。")

    member = Member(
        name=payload.name,
        email=payload.email,
        student_id=payload.student_id,
        team_group=payload.team_group,
        college=payload.college,
        password_hash=hash_password(payload.password),
        role="member",
        status="active",
        identity_locked=True,
    )
    db.add(member)

    try:
        db.flush()
        session_token = create_login_session(db, member)
    except IntegrityError as exc:
        db.rollback()
        if db.scalar(select(Member.id).where(Member.email == payload.email)) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该邮箱已注册，请直接登录。",
            ) from exc
        if db.scalar(select(Member.id).where(Member.student_id == payload.student_id)) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该学号已被使用。",
            ) from exc
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="注册信息已被使用。") from exc

    db.refresh(member)
    set_session_cookie(response, session_token)
    return member
