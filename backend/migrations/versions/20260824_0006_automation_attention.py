"""Add Automation, notification outbox and Attention feedback."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0006"
down_revision: str | None = "20260824_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    automation_type = _enum("automation_type", "ONE_SHOT", "RECURRING", "CONDITION_WATCH")
    automation_status = _enum("automation_status", "ACTIVE", "PAUSED", "COMPLETED", "CANCELLED")
    notification_status = _enum("notification_status", "PENDING", "SUBMITTED_TO_ADAPTER", "FAILED")
    attention_subject_type = _enum("attention_subject_type", "THING", "TASK", "DEADLINE", "BLOCKER")
    bind = op.get_bind()
    for enum in (
        automation_type,
        automation_status,
        notification_status,
        attention_subject_type,
    ):
        enum.create(bind, checkfirst=True)
    op.create_table(
        "automations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("automation_type", automation_type, nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("timezone_name", sa.String(100), nullable=False),
        sa.Column("next_trigger_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("thing_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("recurrence_interval_seconds", sa.Integer(), nullable=True),
        sa.Column("status", automation_status, nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "recurrence_interval_seconds IS NULL OR recurrence_interval_seconds >= 60",
            name="ck_automation_interval",
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["thing_id"], ["things.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_automations_user_key"),
    )
    op.create_index("ix_automations_due", "automations", ["status", "next_trigger_at"])
    op.create_table(
        "automation_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("automation_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_automation_operations_key"),
    )
    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("automation_id", sa.Uuid(), nullable=False),
        sa.Column("occurrence_key", sa.String(300), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("thing_id", sa.Uuid(), nullable=True),
        sa.Column("status", notification_status, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"]),
        sa.ForeignKeyConstraint(["thing_id"], ["things.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("occurrence_key", name="uq_notification_occurrence"),
    )
    op.create_index(
        "ix_notification_outbox_status_created",
        "notification_outbox",
        ["status", "created_at"],
    )
    op.create_table(
        "attention_feedback",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("subject_type", attention_subject_type, nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("last_surfaced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("surface_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "subject_type", "subject_id"),
    )


def downgrade() -> None:
    op.drop_table("attention_feedback")
    op.drop_index("ix_notification_outbox_status_created", table_name="notification_outbox")
    op.drop_table("notification_outbox")
    op.drop_table("automation_operations")
    op.drop_index("ix_automations_due", table_name="automations")
    op.drop_table("automations")
    for name in (
        "attention_subject_type",
        "notification_status",
        "automation_status",
        "automation_type",
    ):
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)
