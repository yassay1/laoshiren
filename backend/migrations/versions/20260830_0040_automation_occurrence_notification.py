"""Phase 6 automation occurrence and notification tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260830_0040"
down_revision: str | None = "20260830_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE automation_type ADD VALUE IF NOT EXISTS 'ONCE'")
    op.execute("ALTER TYPE automation_type ADD VALUE IF NOT EXISTS 'RELATIVE'")
    op.execute("ALTER TYPE automation_type ADD VALUE IF NOT EXISTS 'CONDITION'")

    misfire_policy = postgresql.ENUM(
        "FIRE_ONCE", "SKIP", name="misfire_policy", create_type=False
    )
    occurrence_status = postgresql.ENUM(
        "MATERIALIZED",
        "SUCCEEDED",
        "NOT_MET",
        "FAILED",
        "CANCELLED",
        "SKIPPED",
        name="occurrence_status",
        create_type=False,
    )
    notification_kind = postgresql.ENUM(
        "REMINDER",
        "CONDITION_MET",
        "CONDITION_WATCH_ENDED",
        name="notification_kind",
        create_type=False,
    )
    delivery_status = postgresql.ENUM(
        "READY",
        "ACCEPTED",
        "DELIVERED",
        "FAILED",
        "UNKNOWN_OUTCOME",
        "CANCELLED",
        name="delivery_status",
        create_type=False,
    )
    misfire_policy.create(op.get_bind(), checkfirst=True)
    occurrence_status.create(op.get_bind(), checkfirst=True)
    notification_kind.create(op.get_bind(), checkfirst=True)
    delivery_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "automations",
        sa.Column("definition_revision", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "automations",
        sa.Column(
            "misfire_policy",
            misfire_policy,
            server_default="FIRE_ONCE",
            nullable=False,
        ),
    )

    op.create_table(
        "automation_occurrences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("automation_id", sa.Uuid(), nullable=False),
        sa.Column("definition_revision", sa.Integer(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", occurrence_status, nullable=False),
        sa.Column("durable_job_id", sa.Uuid(), nullable=True),
        sa.Column("materialized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "automation_id",
            "definition_revision",
            "scheduled_for",
            name="uq_automation_occurrence_slot",
        ),
    )
    op.create_index(
        "ix_automation_occurrences_status_created",
        "automation_occurrences",
        ["status", "created_at"],
    )

    op.create_table(
        "push_endpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("push_token", sa.String(length=500), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "notifications_enabled",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
        sa.Column("last_registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "device_id", name="uq_push_endpoints_user_device"),
    )

    op.create_table(
        "notification_intents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", notification_kind, nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("occurrence_id", sa.Uuid(), nullable=False),
        sa.Column("automation_id", sa.Uuid(), nullable=False),
        sa.Column("thing_id", sa.Uuid(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=300), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"]),
        sa.ForeignKeyConstraint(["occurrence_id"], ["automation_occurrences.id"]),
        sa.ForeignKeyConstraint(["thing_id"], ["things.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_notification_intents_dedupe"),
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("intent_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint_id", sa.Uuid(), nullable=False),
        sa.Column("status", delivery_status, nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("provider_message_id", sa.String(length=200), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["endpoint_id"], ["push_endpoints.id"]),
        sa.ForeignKeyConstraint(["intent_id"], ["notification_intents.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "intent_id",
            "endpoint_id",
            name="uq_notification_deliveries_intent_endpoint",
        ),
    )


def downgrade() -> None:
    op.drop_table("notification_deliveries")
    op.drop_table("notification_intents")
    op.drop_table("push_endpoints")
    op.drop_index("ix_automation_occurrences_status_created", table_name="automation_occurrences")
    op.drop_table("automation_occurrences")
    op.drop_column("automations", "misfire_policy")
    op.drop_column("automations", "definition_revision")
    for enum_name in (
        "delivery_status",
        "notification_kind",
        "occurrence_status",
        "misfire_policy",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
