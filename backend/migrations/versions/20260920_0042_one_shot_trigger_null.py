"""Clear the scheduled trigger after one-shot Automation materialization."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260920_0042"
down_revision: str | None = "20260830_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "automations",
        "next_trigger_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
    op.execute(
        "UPDATE automations SET next_trigger_at = NULL "
        "WHERE automation_type::text IN ('ONE_SHOT', 'ONCE', 'RELATIVE') "
        "AND last_triggered_at IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE automations SET next_trigger_at = "
        "COALESCE(last_triggered_at, updated_at, created_at, now()) "
        "WHERE next_trigger_at IS NULL"
    )
    op.alter_column(
        "automations",
        "next_trigger_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
