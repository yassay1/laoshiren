"""Persist active Run wall time without counting WAITING_FOR_USER."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0024"
down_revision: str | None = "20260830_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("active_time_used_ms", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "agent_runs",
        sa.Column("active_started_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        "UPDATE agent_runs SET active_started_at = COALESCE(started_at, updated_at) "
        "WHERE status::text = 'RUNNING'"
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "active_started_at")
    op.drop_column("agent_runs", "active_time_used_ms")
