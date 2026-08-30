"""Add per-claim fencing tokens for Run and Tool execution ownership."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0016"
down_revision: str | None = "20260825_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("claim_token", sa.Uuid()))
    op.add_column("tool_executions", sa.Column("claim_token", sa.Uuid()))
    op.execute(
        "UPDATE tool_executions SET claim_token = gen_random_uuid() WHERE claim_token IS NULL"
    )
    op.alter_column("tool_executions", "claim_token", nullable=False)


def downgrade() -> None:
    op.drop_column("tool_executions", "claim_token")
    op.drop_column("agent_runs", "claim_token")
