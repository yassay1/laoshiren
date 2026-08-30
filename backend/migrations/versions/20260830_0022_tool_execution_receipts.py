"""Add explicit ToolExecution receipt and error reconciliation fields."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260830_0022"
down_revision: str | None = "20260830_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tool_executions", sa.Column("receipt", postgresql.JSONB()))
    op.add_column("tool_executions", sa.Column("error_code", sa.String(length=100)))
    op.add_column(
        "tool_executions",
        sa.Column("provider_idempotency_key", sa.String(length=300)),
    )
    op.add_column("tool_executions", sa.Column("provider_request_id", sa.String(length=300)))
    op.execute(
        "UPDATE tool_executions SET receipt = result "
        "WHERE status::text = 'SUCCEEDED' AND result IS NOT NULL"
    )
    op.execute(
        "UPDATE tool_executions SET error_code = COALESCE(result->>'code', 'TOOL_FAILURE') "
        "WHERE status::text = 'FAILED'"
    )
    op.execute(
        "UPDATE tool_executions SET error_code = 'UNKNOWN_OUTCOME' "
        "WHERE status::text = 'UNKNOWN_OUTCOME'"
    )


def downgrade() -> None:
    op.drop_column("tool_executions", "provider_request_id")
    op.drop_column("tool_executions", "provider_idempotency_key")
    op.drop_column("tool_executions", "error_code")
    op.drop_column("tool_executions", "receipt")
