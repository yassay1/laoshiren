"""Add durable Thread, Message, Run and Run Event resources."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0007"
down_revision: str | None = "20260824_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    message_role = _enum("message_role", "USER", "ASSISTANT", "SYSTEM_EVENT")
    run_trigger = _enum("run_trigger", "USER_MESSAGE", "AUTOMATION", "SYSTEM_EVENT")
    run_status = _enum(
        "run_status", "QUEUED", "RUNNING", "WAITING_USER", "COMPLETED", "FAILED", "CANCELLED"
    )
    run_event_type = _enum(
        "run_event_type",
        "run.started",
        "assistant.delta",
        "assistant.message",
        "tool.started",
        "tool.completed",
        "tool.failed",
        "status.updated",
        "interrupt.required",
        "run.completed",
        "run.failed",
        "heartbeat",
    )
    bind = op.get_bind()
    for enum in (message_role, run_trigger, run_status, run_event_type):
        enum.create(bind, checkfirst=True)

    op.create_table(
        "threads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("active_thing_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["active_thing_id"], ["things.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_threads_user_key"),
    )
    op.create_index("ix_threads_user_updated", "threads", ["user_id", "updated_at"])

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("trigger", run_trigger, nullable=False),
        sa.Column("input_message_id", sa.Uuid(), nullable=True),
        sa.Column("status", run_status, nullable=False),
        sa.Column("current_phase", sa.String(100), nullable=True),
        sa.Column("status_label", sa.String(300), nullable=True),
        sa.Column("final_message_id", sa.Uuid(), nullable=True),
        sa.Column("interrupt_id", sa.Uuid(), nullable=True),
        sa.Column("interrupt", postgresql.JSONB(), nullable=True),
        sa.Column("resume_payload", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("event_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_agent_runs_user_key"),
    )
    op.create_index(
        "ix_agent_runs_thread_created", "agent_runs", ["thread_id", "created_at"]
    )
    op.create_index(
        "ix_agent_runs_status_updated", "agent_runs", ["status", "updated_at"]
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("role", message_role, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "source_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False
        ),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"]),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_messages_thread_created", "messages", ["thread_id", "created_at"]
    )

    op.create_table(
        "run_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", run_event_type, nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_run_events_sequence"),
    )
    op.create_index(
        "ix_run_events_run_sequence", "run_events", ["run_id", "sequence"]
    )

    op.create_table(
        "run_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("operation", sa.String(30), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_run_operations_key"),
    )


def downgrade() -> None:
    op.drop_table("run_operations")
    op.drop_index("ix_run_events_run_sequence", table_name="run_events")
    op.drop_table("run_events")
    op.drop_index("ix_messages_thread_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_agent_runs_status_updated", table_name="agent_runs")
    op.drop_index("ix_agent_runs_thread_created", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_threads_user_updated", table_name="threads")
    op.drop_table("threads")
    for name in ("run_event_type", "run_status", "run_trigger", "message_role"):
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)
