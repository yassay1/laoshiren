"""Add independent Task due-time and recurrence fields."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0032"
down_revision: str | None = "20260830_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("recurrence_interval_days", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_tasks_recurrence_requires_due",
        "tasks",
        "recurrence_interval_days IS NULL OR (recurrence_interval_days > 0 AND due_at IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tasks_recurrence_requires_due", "tasks", type_="check")
    op.drop_column("tasks", "recurrence_interval_days")
    op.drop_column("tasks", "due_at")
