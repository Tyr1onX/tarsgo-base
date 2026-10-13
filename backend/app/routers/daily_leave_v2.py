from __future__ import annotations

import io
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import get_current_member, new_token, require_admin
from ..college_dictionary import COLLEGE_BY_CODE
from ..db import get_db
from ..leave_documents import DOCX_MIME_TYPE, build_daily_leave_v2_docx
from ..models import DailyLeaveEntry, DailyLeaveWindow, Member
from ..schemas import (
    DailyLeavePublicEntryCreate,
    DailyLeavePublicWindowOut,
    DailyLeaveWindowAdminOut,
    DailyLeaveWindowCreate,
    DailyLeaveWindowMemberOut,
    DailyLeaveSelfServiceCreate,
    DailyLeaveDocumentReadyOut,
    validate_college,
    validate_member_name,
    validate_student_id,
)
from ..school_leave import get_leave_contact_phone, school_leave_now


router = APIRouter(prefix="/api/daily-leave", tags=["daily-leave-v2"])


def _accepting(window: DailyLeaveWindow, *, now: datetime | None = None) -> bool:
    current_time = now or school_leave_now()
    return window.status == "open" and window.open_until > current_time and window.end_at > current_time


def _member_window_out(window: DailyLeaveWindow) -> DailyLeaveWindowMemberOut:
    return DailyLeaveWindowMemberOut(
        id=window.id,
        title=window.title,
        start_at=window.start_at,
        end_at=window.end_at,
        open_until=window.open_until,
        status=window.status,
        accepting_participants=_accepting(window),
    )


def _admin_window_out(db: Session, window: DailyLeaveWindow) -> DailyLeaveWindowAdminOut:
    entry_count = db.scalar(
        select(func.count(DailyLeaveEntry.id)).where(DailyLeaveEntry.window_id == window.id)
    ) or 0
    return DailyLeaveWindowAdminOut(
        id=window.id,
        title=window.title,
        start_at=window.start_at,
        end_at=window.end_at,
        open_until=window.open_until,
        team_open=window.team_open,
        public_enabled=window.public_enabled,
        status=window.status,
        accepting_participants=_accepting(window),
        entry_count=int(entry_count),
        public_path=f"/leave/daily/{window.public_token}" if window.public_token else None,
        created_at=window.created_at,
    )


def _get_window(db: Session, window_id: int, *, lock: bool = False) -> DailyLeaveWindow:
    query = select(DailyLeaveWindow).where(DailyLeaveWindow.id == window_id)
    if lock:
        query = query.with_for_update()
    window = db.scalar(query)
    if window is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="请假窗口不存在")
    return window


def _require_open(window: DailyLeaveWindow, *, public: bool) -> None:
    if window.status != "open":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="请假窗口已关闭")
    now = school_leave_now()
    if window.open_until <= now or window.end_at <= now:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="共享活动已结束")
    if public and (not window.public_enabled or not window.public_token):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="临时报名链接无效")
    if not public and not window.team_open:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="请假窗口不存在")


def _public_window(token: str, db: Session, *, lock: bool = False) -> DailyLeaveWindow:
    if not 40 <= len(token) <= 50 or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in token
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="临时报名链接无效")
    query = select(DailyLeaveWindow).where(
        DailyLeaveWindow.public_token == token,
        DailyLeaveWindow.public_enabled.is_(True),
    )
    if lock:
        query = query.with_for_update()
    window = db.scalar(query)
    if window is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="临时报名链接无效")
    return window


def _document_response(content: bytes, filename: str) -> StreamingResponse:
    return StreamingResponse(
        io.BytesIO(content),
        media_type=DOCX_MIME_TYPE,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


def _document_ready(download_url: str, filename: str) -> DailyLeaveDocumentReadyOut:
    return DailyLeaveDocumentReadyOut(download_url=download_url, filename=filename)


def _make_document(
    *, start_at: datetime, end_at: datetime, name: str, student_id: str, college: str, offline: bool
):
    phone = get_leave_contact_phone()
    if not phone:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LEAVE_CONTACT_PHONE 未配置，暂时不能生成请假材料",
        )
    return build_daily_leave_v2_docx(
        start_at=start_at,
        end_at=end_at,
        name=name,
        student_id=student_id,
        college_name=COLLEGE_BY_CODE[college]["name"],
        contact_phone=phone,
        offline=offline,
    )


def _daily_filename(start_at: datetime, *, offline: bool) -> str:
    kind = "线下签章版" if offline else "请假条"
    return f"{kind}_{start_at:%Y-%m-%d}.docx"


def _member_identity(current: Member) -> tuple[str, str, str]:
    try:
        return (
            validate_member_name(current.name or ""),
            validate_student_id(current.student_id or ""),
            validate_college(current.college or ""),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="请先完善个人资料中的姓名、8 位学号和学院",
        ) from exc


@router.get("/windows", response_model=list[DailyLeaveWindowMemberOut])
def member_windows(
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> list[DailyLeaveWindowMemberOut]:
    now = school_leave_now()
    windows = list(
        db.scalars(
            select(DailyLeaveWindow)
            .where(
                DailyLeaveWindow.team_open.is_(True),
                DailyLeaveWindow.status == "open",
                DailyLeaveWindow.open_until > now,
            )
            .order_by(DailyLeaveWindow.start_at, DailyLeaveWindow.id)
        )
    )
    return [_member_window_out(window) for window in windows]


@router.get("/admin/windows", response_model=list[DailyLeaveWindowAdminOut])
def admin_windows(
    _: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[DailyLeaveWindowAdminOut]:
    windows = list(
        db.scalars(select(DailyLeaveWindow).order_by(DailyLeaveWindow.start_at.desc(), DailyLeaveWindow.id.desc()))
    )
    return [_admin_window_out(db, window) for window in windows]


@router.post("/admin/windows", response_model=DailyLeaveWindowAdminOut, status_code=status.HTTP_201_CREATED)
def create_window(
    payload: DailyLeaveWindowCreate,
    current: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DailyLeaveWindowAdminOut:
    if payload.open_until <= school_leave_now():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="开放截止时间必须晚于当前时间")
    window = DailyLeaveWindow(
        title=payload.title,
        start_at=payload.start_at,
        end_at=payload.end_at,
        open_until=payload.open_until or payload.end_at,
        team_open=payload.team_open,
        public_enabled=payload.public_enabled,
        public_token=new_token() if payload.public_enabled else None,
        status="open",
        created_by=current.id,
    )
    db.add(window)
    db.commit()
    db.refresh(window)
    return _admin_window_out(db, window)


@router.post("/admin/windows/{window_id}/public-link", response_model=DailyLeaveWindowAdminOut)
def enable_public_link(
    window_id: int,
    _: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DailyLeaveWindowAdminOut:
    window = _get_window(db, window_id, lock=True)
    if not _accepting(window):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="共享活动已结束或关闭")
    if not window.public_enabled or not window.public_token:
        window.public_enabled = True
        window.public_token = new_token()
        db.commit()
        db.refresh(window)
    return _admin_window_out(db, window)


@router.post("/admin/windows/{window_id}/close", response_model=DailyLeaveWindowAdminOut)
def close_window(
    window_id: int,
    _: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DailyLeaveWindowAdminOut:
    window = _get_window(db, window_id, lock=True)
    if window.status != "closed":
        window.status = "closed"
        db.commit()
        db.refresh(window)
    return _admin_window_out(db, window)


@router.post("/windows/{window_id}/document", response_model=DailyLeaveDocumentReadyOut)
def member_document(
    window_id: int,
    offline: bool = False,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> DailyLeaveDocumentReadyOut:
    window = _get_window(db, window_id, lock=True)
    _require_open(window, public=False)
    entry = db.scalar(
        select(DailyLeaveEntry)
        .where(DailyLeaveEntry.window_id == window.id, DailyLeaveEntry.member_id == current.id)
        .with_for_update()
    )
    if entry is None:
        name, student_id, college = _member_identity(current)
        collision = db.scalar(
            select(DailyLeaveEntry).where(
                DailyLeaveEntry.window_id == window.id,
                DailyLeaveEntry.student_id_snapshot == student_id,
            )
        )
        if collision is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该学号已在本窗口生成材料")
        entry = DailyLeaveEntry(
            window_id=window.id,
            member_id=current.id,
            name_snapshot=name,
            student_id_snapshot=student_id,
            college_snapshot=college,
            participant_type=current.team_membership or "other",
            start_at=None,
            end_at=None,
        )
        db.add(entry)
        try:
            db.commit()
            db.refresh(entry)
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该学号已在本窗口生成材料") from exc

    content = _make_document(
        start_at=window.start_at,
        end_at=window.end_at,
        name=entry.name_snapshot,
        student_id=entry.student_id_snapshot,
        college=entry.college_snapshot,
        offline=offline,
    )
    filename = _daily_filename(window.start_at, offline=offline)
    download_url = f"/api/daily-leave/windows/{window.id}/document"
    if offline:
        download_url += "?offline=true"
    return _document_ready(download_url, filename)


@router.get("/windows/{window_id}/document")
def member_document_download(
    window_id: int,
    offline: bool = False,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    window = _get_window(db, window_id)
    entry = db.scalar(
        select(DailyLeaveEntry).where(
            DailyLeaveEntry.window_id == window.id,
            DailyLeaveEntry.member_id == current.id,
        )
    )
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="请先生成该共享活动的请假材料")
    content = _make_document(
        start_at=window.start_at,
        end_at=window.end_at,
        name=entry.name_snapshot,
        student_id=entry.student_id_snapshot,
        college=entry.college_snapshot,
        offline=offline,
    )
    return _document_response(content, _daily_filename(window.start_at, offline=offline))


@router.post("/self-service/document", response_model=DailyLeaveDocumentReadyOut)
def self_service_document(
    payload: DailyLeaveSelfServiceCreate,
    offline: bool = False,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> DailyLeaveDocumentReadyOut:
    # Serialize self-service upserts on the member row. This makes the following
    # current read safe under MySQL REPEATABLE READ without a schema migration.
    db.scalar(select(Member.id).where(Member.id == current.id).with_for_update())
    entry = db.scalar(
        select(DailyLeaveEntry)
        .where(
            DailyLeaveEntry.window_id.is_(None),
            DailyLeaveEntry.member_id == current.id,
            DailyLeaveEntry.start_at == payload.start_at,
            DailyLeaveEntry.end_at == payload.end_at,
        )
        .with_for_update()
    )
    if entry is None:
        name, student_id, college = _member_identity(current)
        entry = DailyLeaveEntry(
            window_id=None,
            member_id=current.id,
            start_at=payload.start_at,
            end_at=payload.end_at,
            name_snapshot=name,
            student_id_snapshot=student_id,
            college_snapshot=college,
            participant_type=current.team_membership or "other",
        )
        db.add(entry)
        db.flush()
    _make_document(
        start_at=entry.start_at or payload.start_at,
        end_at=entry.end_at or payload.end_at,
        name=entry.name_snapshot,
        student_id=entry.student_id_snapshot,
        college=entry.college_snapshot,
        offline=offline,
    )
    db.commit()
    filename = _daily_filename(payload.start_at, offline=offline)
    download_url = f"/api/daily-leave/self-service/document/{entry.id}"
    if offline:
        download_url += "?offline=true"
    return _document_ready(download_url, filename)


@router.get("/self-service/document/{entry_id}")
def self_service_document_download(
    entry_id: int,
    offline: bool = False,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    entry = db.scalar(
        select(DailyLeaveEntry).where(
            DailyLeaveEntry.id == entry_id,
            DailyLeaveEntry.window_id.is_(None),
            DailyLeaveEntry.member_id == current.id,
        )
    )
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="请先生成该时段的请假材料")
    if entry.start_at is None or entry.end_at is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该记录没有有效的请假时段")
    content = _make_document(
        start_at=entry.start_at,
        end_at=entry.end_at,
        name=entry.name_snapshot,
        student_id=entry.student_id_snapshot,
        college=entry.college_snapshot,
        offline=offline,
    )
    return _document_response(content, _daily_filename(entry.start_at, offline=offline))


@router.get("/public/{token}", response_model=DailyLeavePublicWindowOut)
def public_window(token: str, db: Session = Depends(get_db)) -> DailyLeavePublicWindowOut:
    window = _public_window(token, db)
    if not _accepting(window):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="临时链接已失效")
    return DailyLeavePublicWindowOut(
        start_at=window.start_at,
        end_at=window.end_at,
        accepting_participants=True,
    )


@router.post("/public/{token}/document", response_model=DailyLeaveDocumentReadyOut)
def public_document(
    token: str,
    payload: DailyLeavePublicEntryCreate,
    offline: bool = False,
    db: Session = Depends(get_db),
) -> DailyLeaveDocumentReadyOut:
    window = _public_window(token, db, lock=True)
    _require_open(window, public=True)
    entry = db.scalar(
        select(DailyLeaveEntry)
        .where(
            DailyLeaveEntry.window_id == window.id,
            DailyLeaveEntry.student_id_snapshot == payload.student_id,
        )
        .with_for_update()
    )
    if entry is None:
        entry = DailyLeaveEntry(
            window_id=window.id,
            member_id=None,
            name_snapshot=payload.name,
            student_id_snapshot=payload.student_id,
            college_snapshot=payload.college,
            participant_type="other",
        )
        db.add(entry)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            # A concurrent repeat still resolves to the original snapshot.
            entry = db.scalar(
                select(DailyLeaveEntry).where(
                    DailyLeaveEntry.window_id == window.id,
                    DailyLeaveEntry.student_id_snapshot == payload.student_id,
                )
            )
            if entry is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="请稍后重新生成") from exc
    content = _make_document(
        start_at=window.start_at,
        end_at=window.end_at,
        name=entry.name_snapshot,
        student_id=entry.student_id_snapshot,
        college=entry.college_snapshot,
        offline=offline,
    )
    filename = _daily_filename(window.start_at, offline=offline)
    download_url = f"/api/daily-leave/public/{token}/document/{entry.id}"
    if offline:
        download_url += "?offline=true"
    return _document_ready(download_url, filename)


@router.get("/public/{token}/document/{entry_id}")
def public_document_download(
    token: str,
    entry_id: int,
    offline: bool = False,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    window = _public_window(token, db)
    entry = db.scalar(
        select(DailyLeaveEntry).where(
            DailyLeaveEntry.id == entry_id,
            DailyLeaveEntry.window_id == window.id,
        )
    )
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="请先提交本人的报名信息")
    content = _make_document(
        start_at=window.start_at,
        end_at=window.end_at,
        name=entry.name_snapshot,
        student_id=entry.student_id_snapshot,
        college=entry.college_snapshot,
        offline=offline,
    )
    return _document_response(content, _daily_filename(window.start_at, offline=offline))
