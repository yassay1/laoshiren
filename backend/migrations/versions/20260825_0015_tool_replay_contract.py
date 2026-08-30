"""Persist Tool replay safety and downstream idempotency contracts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0015"
down_revision: str | None = "20260825_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_executions",
        sa.Column("replay_safe", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("tool_executions", sa.Column("idempotency_key", sa.String(300)))


def downgrade() -> None:
    op.drop_column("tool_executions", "idempotency_key")
    op.drop_column("tool_executions", "replay_safe")
