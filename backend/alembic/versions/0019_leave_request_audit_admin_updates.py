"""record leave document requests and per-admin updates

Revision ID: 0019_leave_admin_updates
Revises: 0018_leave_security
Create Date: 2026-10-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019_leave_admin_updates"
down_revision: Union[str, Sequence[str], None] = "0018_leave_security"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_leave_document_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_member_id", sa.Integer(), nullable=True),
        sa.Column("request_type", sa.String(length=30), nullable=False),
        sa.Column("file_version", sa.String(length=50), nullable=False),
        sa.Column("offline", sa.Boolean(), nullable=False),
        sa.Column("requested_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "request_type IN ('first_generation','repeat_download')",
            name="ck_daily_leave_document_requests_type",
        ),
        sa.ForeignKeyConstraint(["entry_id"], ["daily_leave_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_member_id"], ["members.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_daily_leave_document_requests_entry_requested",
        "daily_leave_document_requests",
        ["entry_id", "requested_at"],
    )

    op.create_table(
        "admin_update_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_type", "entity_type", "entity_id", name="uq_admin_update_event_entity"
        ),
    )
    op.create_index("ix_admin_update_events_created", "admin_update_events", ["created_at"])

    op.create_table(
        "admin_update_reads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("read_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["admin_update_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["admin_id"], ["members.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "admin_id", name="uq_admin_update_reads_event_admin"),
    )
    op.create_index("ix_admin_update_reads_admin", "admin_update_reads", ["admin_id"])


def downgrade() -> None:
    op.drop_index("ix_admin_update_reads_admin", table_name="admin_update_reads")
    op.drop_table("admin_update_reads")
    op.drop_index("ix_admin_update_events_created", table_name="admin_update_events")
    op.drop_table("admin_update_events")
    op.drop_index(
        "ix_daily_leave_document_requests_entry_requested",
        table_name="daily_leave_document_requests",
    )
    op.drop_table("daily_leave_document_requests")
