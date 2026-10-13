"""secure public leave downloads and lock registered identities

Revision ID: 0018_leave_security
Revises: 0017_independent_tasks
Create Date: 2026-10-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018_leave_security"
down_revision: Union[str, Sequence[str], None] = "0017_independent_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "members",
        sa.Column("identity_locked", sa.Boolean(), server_default=sa.text("0"), nullable=False),
    )
    # Existing activated/disabled accounts predate the explicit onboarding flag.
    # Invited accounts remain unlocked so their first activation can collect identity data.
    op.execute("UPDATE members SET identity_locked = 1 WHERE status IN ('active','disabled')")

    op.add_column(
        "daily_leave_entries",
        sa.Column("public_download_token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "daily_leave_entries",
        sa.Column("public_download_expires_at", sa.DateTime(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_daily_leave_entries_public_download_token_hash",
        "daily_leave_entries",
        ["public_download_token_hash"],
    )
    op.create_check_constraint(
        "ck_daily_leave_entries_public_download_token_pair",
        "daily_leave_entries",
        "(public_download_token_hash IS NULL AND public_download_expires_at IS NULL) OR "
        "(public_download_token_hash IS NOT NULL AND public_download_expires_at IS NOT NULL)",
    )

    op.create_table(
        "member_identity_audits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=True),
        sa.Column("field", sa.String(length=20), nullable=False),
        sa.Column("old_value", sa.String(length=100), nullable=True),
        sa.Column("new_value", sa.String(length=100), nullable=True),
        sa.Column("changed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("field IN ('name','student_id')", name="ck_member_identity_audits_field"),
        sa.ForeignKeyConstraint(["admin_id"], ["members.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_member_identity_audits_member_changed",
        "member_identity_audits",
        ["member_id", "changed_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_member_identity_audits_member_changed", table_name="member_identity_audits")
    op.drop_table("member_identity_audits")
    op.drop_constraint(
        "ck_daily_leave_entries_public_download_token_pair",
        "daily_leave_entries",
        type_="check",
    )
    op.drop_constraint(
        "uq_daily_leave_entries_public_download_token_hash",
        "daily_leave_entries",
        type_="unique",
    )
    op.drop_column("daily_leave_entries", "public_download_expires_at")
    op.drop_column("daily_leave_entries", "public_download_token_hash")
    op.drop_column("members", "identity_locked")
