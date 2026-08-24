"""Add Run leases and durable Tool execution ledger."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0009"
down_revision: str | None = "20260824_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("claim_owner", sa.String(200)))
    op.add_column(
        "agent_runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True))
    )
    op.add_column("agent_runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True)))
    op.add_column(
        "agent_runs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_agent_runs_status_lease",
        "agent_runs",
        ["status", "lease_expires_at"],
    )

    status = postgresql.ENUM(
        "RUNNING", "SUCCEEDED", "FAILED", name="tool_execution_status"
    )
    status.create(op.get_bind(), checkfirst=True)
    status_column = postgresql.ENUM(
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        name="tool_execution_status",
        create_type=False,
    )
    op.create_table(
        "tool_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.String(200), nullable=False),
        sa.Column("tool_name", sa.String(200), nullable=False),
        sa.Column("arguments_hash", sa.String(64), nullable=False),
        sa.Column("status", status_column, nullable=False),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("claim_owner", sa.String(200), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "attempt_count", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "action_id", name="uq_tool_executions_action"),
    )
    op.create_index(
        "ix_tool_executions_status_lease",
        "tool_executions",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tool_executions_status_lease", table_name="tool_executions")
    op.drop_table("tool_executions")
    postgresql.ENUM(name="tool_execution_status").drop(
        op.get_bind(), checkfirst=True
    )
    op.drop_index("ix_agent_runs_status_lease", table_name="agent_runs")
    op.drop_column("agent_runs", "attempt_count")
    op.drop_column("agent_runs", "heartbeat_at")
    op.drop_column("agent_runs", "lease_expires_at")
    op.drop_column("agent_runs", "claim_owner")
