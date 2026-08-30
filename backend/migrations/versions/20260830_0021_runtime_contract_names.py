"""Align frozen Run and Tool Ledger status names with V2.2."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260830_0021"
down_revision: str | None = "20260830_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE run_status RENAME VALUE 'WAITING_USER' TO 'WAITING_FOR_USER'")
    op.execute("ALTER TYPE tool_execution_status RENAME VALUE 'RUNNING' TO 'IN_PROGRESS'")
    op.execute("ALTER TYPE tool_execution_status RENAME VALUE 'UNKNOWN' TO 'UNKNOWN_OUTCOME'")


def downgrade() -> None:
    op.execute("ALTER TYPE tool_execution_status RENAME VALUE 'UNKNOWN_OUTCOME' TO 'UNKNOWN'")
    op.execute("ALTER TYPE tool_execution_status RENAME VALUE 'IN_PROGRESS' TO 'RUNNING'")
    op.execute("ALTER TYPE run_status RENAME VALUE 'WAITING_FOR_USER' TO 'WAITING_USER'")
