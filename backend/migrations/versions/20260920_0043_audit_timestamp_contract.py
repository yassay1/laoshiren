"""Align required audit timestamp columns with the project ORM contract."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260920_0043"
down_revision: str | None = "20260920_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUDIT_COLUMNS: dict[str, tuple[str, ...]] = {
    "agent_runs": ("created_at", "updated_at"),
    "attention_feedback": ("updated_at",),
    "automation_operations": ("created_at",),
    "automations": ("created_at", "updated_at"),
    "blockers": ("created_at", "updated_at"),
    "durable_jobs": ("created_at", "updated_at"),
    "file_processing_generations": ("created_at",),
    "files": ("created_at",),
    "long_term_memories": ("created_at", "updated_at"),
    "memory_operations": ("created_at",),
    "message_attachments": ("created_at",),
    "messages": ("created_at",),
    "notification_outbox": ("created_at", "updated_at"),
    "retrieval_segments": ("created_at",),
    "run_events": ("occurred_at",),
    "run_interactions": ("created_at",),
    "run_operations": ("created_at",),
    "source_chunks": ("created_at",),
    "sources": ("created_at",),
    "thing_relations": ("created_at",),
    "thing_sources": ("created_at",),
    "threads": ("created_at", "updated_at"),
    "tool_executions": ("created_at", "updated_at"),
    "web_observations": ("created_at",),
}


def upgrade() -> None:
    for table, columns in AUDIT_COLUMNS.items():
        for column in columns:
            if column == "created_at" and "updated_at" in columns:
                fallback = "COALESCE(updated_at, now())"
            elif column == "updated_at" and "created_at" in columns:
                fallback = "COALESCE(created_at, now())"
            else:
                fallback = "now()"
            op.execute(
                f'UPDATE "{table}" SET "{column}" = {fallback} WHERE "{column}" IS NULL'
            )
            op.alter_column(
                table,
                column,
                existing_type=sa.DateTime(timezone=True),
                nullable=False,
            )


def downgrade() -> None:
    for table, columns in reversed(tuple(AUDIT_COLUMNS.items())):
        for column in reversed(columns):
            op.alter_column(
                table,
                column,
                existing_type=sa.DateTime(timezone=True),
                nullable=True,
            )
