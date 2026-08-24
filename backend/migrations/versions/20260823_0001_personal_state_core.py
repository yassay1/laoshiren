"""Create the Personal State core tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260823_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    thing_status = sa.Enum(
        "PLANNING",
        "ACTIVE",
        "BLOCKED",
        "WAITING",
        "PAUSED",
        "COMPLETED",
        "CANCELLED",
        "ARCHIVED",
        name="thing_status",
    )
    task_status = sa.Enum(
        "TODO", "IN_PROGRESS", "WAITING", "BLOCKED", "DONE", "CANCELLED", name="task_status"
    )
    date_certainty = sa.Enum(
        "CONFIRMED", "PROBABLE", "UNCONFIRMED", "DISPUTED", name="date_certainty"
    )
    date_precision = sa.Enum("DATE", "DATETIME", name="date_precision")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "things",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", thing_status, nullable=False),
        sa.Column("current_stage", sa.String(200), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_things_user_updated", "things", ["user_id", "updated_at"])
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "thing_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("things.id"), nullable=False
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("status", task_status, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_tasks_thing_status", "tasks", ["thing_id", "status"])
    op.create_table(
        "thing_dates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "thing_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("things.id"), nullable=False
        ),
        sa.Column("kind", sa.String(80), nullable=False),
        sa.Column("value", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone_name", sa.String(64), nullable=False),
        sa.Column("precision", date_precision, nullable=False),
        sa.Column("certainty", date_certainty, nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_thing_dates_thing_kind", "thing_dates", ["thing_id", "kind"])
    op.create_table(
        "state_mutations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "thing_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("things.id"), nullable=False
        ),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_id", sa.String(120), nullable=False),
        sa.Column("mutation_type", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(80), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "timeline_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "thing_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("things.id"), nullable=False
        ),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "mutation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("state_mutations.id"),
            nullable=True,
        ),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_timeline_thing_occurred", "timeline_events", ["thing_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_timeline_thing_occurred", table_name="timeline_events")
    op.drop_table("timeline_events")
    op.drop_table("state_mutations")
    op.drop_index("ix_thing_dates_thing_kind", table_name="thing_dates")
    op.drop_table("thing_dates")
    op.drop_index("ix_tasks_thing_status", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_things_user_updated", table_name="things")
    op.drop_table("things")
    op.drop_table("users")
    sa.Enum(name="date_precision").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="date_certainty").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="task_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="thing_status").drop(op.get_bind(), checkfirst=True)
