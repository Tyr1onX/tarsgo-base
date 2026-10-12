"""distinguish standalone tasks from operations items

Revision ID: 0017_independent_tasks
Revises: 0016_daily_leave_self_service
Create Date: 2026-10-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017_independent_tasks"
down_revision: Union[str, Sequence[str], None] = "0016_daily_leave_self_service"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("kind", sa.String(length=20), server_default="item", nullable=False),
    )
    op.execute("UPDATE tasks SET kind = 'task' WHERE parent_id IS NOT NULL")
    op.create_check_constraint(
        "ck_tasks_kind",
        "tasks",
        "kind IN ('item','task') AND (parent_id IS NULL OR kind = 'task')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tasks_kind", "tasks", type_="check")
    op.drop_column("tasks", "kind")
