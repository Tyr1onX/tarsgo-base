from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..auth import hash_password, hash_token, utcnow
from ..db import get_db
from ..models import Invitation, Member
from ..schemas import InvitationAccept, InvitationInfo

router = APIRouter(prefix="/api/invitations", tags=["invitations"])


def _get_invitation(db: Session, token: str, *, lock: bool = False) -> Invitation:
    query = (
        select(Invitation)
        .options(joinedload(Invitation.member))
        .where(Invitation.token_hash == hash_token(token))
    )
    if lock:
        query = query.with_for_update()
    invitation = db.scalar(query)
    if not invitation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="邀请无效")
    if invitation.expires_at <= utcnow():
        db.delete(invitation)
        db.commit()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="邀请已过期，请联系管理员重新生成")
    if invitation.member.status != "invited":
        db.delete(invitation)
        db.commit()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="邀请已失效")
    return invitation


@router.get("/{token}", response_model=InvitationInfo)
def invitation_info(token: str, db: Session = Depends(get_db)) -> InvitationInfo:
    invitation = _get_invitation(db, token)
    return InvitationInfo(
        name=invitation.member.name,
        email=invitation.member.email,
        student_id=invitation.member.student_id,
        college=invitation.member.college,
        expires_at=invitation.expires_at,
    )


@router.post("/{token}/accept", status_code=status.HTTP_204_NO_CONTENT)
def accept_invitation(token: str, payload: InvitationAccept, db: Session = Depends(get_db)) -> None:
    invitation = _get_invitation(db, token, lock=True)
    member = invitation.member
    duplicate_student_id = db.scalar(
        select(Member.id).where(
            Member.student_id == payload.student_id,
            Member.id != member.id,
        )
    )
    if duplicate_student_id is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该学号已被使用")

    member.name = payload.name
    member.student_id = payload.student_id
    member.college = payload.college
    member.identity_locked = True
    member.password_hash = hash_password(payload.password)
    member.status = "active"
    db.delete(invitation)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该学号已被使用") from exc
