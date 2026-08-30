"""Represent ambiguous external Tool outcomes explicitly."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260825_0017"
down_revision: str | None = "20260825_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE tool_execution_status ADD VALUE IF NOT EXISTS 'UNKNOWN'")


def downgrade() -> None:
    op.execute("UPDATE tool_executions SET status = 'FAILED' WHERE status = 'UNKNOWN'")
    op.execute(
        "ALTER TABLE tool_executions ALTER COLUMN status TYPE varchar(20) USING status::text"
    )
    op.execute("DROP TYPE tool_execution_status")
    op.execute("CREATE TYPE tool_execution_status AS ENUM ('RUNNING', 'SUCCEEDED', 'FAILED')")
    op.execute(
        "ALTER TABLE tool_executions ALTER COLUMN status "
        "TYPE tool_execution_status USING status::tool_execution_status"
    )
