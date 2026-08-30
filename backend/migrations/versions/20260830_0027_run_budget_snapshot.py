"""Freeze runtime budget limits at Run acceptance."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260830_0027"
down_revision: str | None = "20260830_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column(
            "budget_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("agent_runs", "budget_snapshot", server_default=None)


def downgrade() -> None:
    op.drop_column("agent_runs", "budget_snapshot")
