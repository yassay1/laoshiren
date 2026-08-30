"""Persist terminal graph output before product finalization."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260830_0025"
down_revision: str | None = "20260830_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("terminal_output", postgresql.JSONB()))
    op.add_column("agent_runs", sa.Column("graph_terminal_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("agent_runs", "graph_terminal_at")
    op.drop_column("agent_runs", "terminal_output")
