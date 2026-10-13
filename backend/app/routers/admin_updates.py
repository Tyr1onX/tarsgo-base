from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..db import get_db
from ..models import AdminUpdateEvent, AdminUpdateRead, Member
from ..schemas import AdminUpdateMarkReadIn, AdminUpdateMarkReadOut, AdminUpdateUnreadCountOut


router = APIRouter(prefix="/api/admin-updates", tags=["admin-updates"])


def _unread_count(db: Session, admin_id: int) -> int:
    return int(
        db.scalar(
            select(func.count(AdminUpdateEvent.id))
            .outerjoin(
                AdminUpdateRead,
                and_(
                    AdminUpdateRead.event_id == AdminUpdateEvent.id,
                    AdminUpdateRead.admin_id == admin_id,
                ),
            )
            .where(AdminUpdateRead.id.is_(None))
        )
        or 0
    )


@router.get("/unread-count", response_model=AdminUpdateUnreadCountOut)
def unread_count(
    current: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUpdateUnreadCountOut:
    return AdminUpdateUnreadCountOut(unread_count=_unread_count(db, current.id))


@router.post("/read", response_model=AdminUpdateMarkReadOut)
def mark_read(
    payload: AdminUpdateMarkReadIn,
    current: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUpdateMarkReadOut:
    existing_ids = list(
        db.scalars(select(AdminUpdateEvent.id).where(AdminUpdateEvent.id.in_(payload.event_ids)))
    )
    if existing_ids:
        db.execute(
            mysql_insert(AdminUpdateRead)
            .values([{"event_id": event_id, "admin_id": current.id} for event_id in existing_ids])
            .on_duplicate_key_update(read_at=AdminUpdateRead.read_at)
        )
        db.commit()
    return AdminUpdateMarkReadOut(
        marked_count=len(existing_ids),
        unread_count=_unread_count(db, current.id),
    )
