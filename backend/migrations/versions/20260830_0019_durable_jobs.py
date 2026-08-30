"""Add the shared PostgreSQL durable work queue."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260830_0019"
down_revision: str | None = "20260825_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    job_kind = postgresql.ENUM(
        "AGENT_RUN",
        "FILE_PROCESSING",
        "MEMORY_FORMATION",
        "AUTOMATION_OCCURRENCE",
        "PUSH_DELIVERY",
        "ACCOUNT_DELETION",
        name="durable_job_kind",
        create_type=False,
    )
    job_status = postgresql.ENUM(
        "READY",
        "CLAIMED",
        "PAUSED",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        name="durable_job_status",
        create_type=False,
    )
    job_kind.create(op.get_bind(), checkfirst=True)
    job_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "durable_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", job_kind, nullable=False),
        sa.Column("dedupe_key", sa.String(length=300), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", job_status, nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivery_attempt", sa.Integer(), nullable=False),
        sa.Column("max_delivery_attempts", sa.Integer(), nullable=False),
        sa.Column("claimed_by", sa.String(length=200)),
        sa.Column("claim_epoch", sa.Integer(), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(length=100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_durable_jobs_user_dedupe"),
    )
    op.create_index(
        "ix_durable_jobs_ready_claim",
        "durable_jobs",
        ["status", "available_at", "priority", "created_at"],
    )
    op.create_index("ix_durable_jobs_lease", "durable_jobs", ["status", "lease_until"])
    op.execute(
        """
        INSERT INTO durable_jobs (
            id, user_id, kind, dedupe_key, payload, status, priority,
            available_at, delivery_attempt, max_delivery_attempts,
            claim_epoch, created_at, updated_at
        )
        SELECT
            gen_random_uuid(), user_id, 'AGENT_RUN', 'agent-run:' || id::text,
            jsonb_build_object('run_id', id::text),
            CASE WHEN status::text = 'WAITING_USER' THEN 'PAUSED'::durable_job_status
                 ELSE 'READY'::durable_job_status END,
            0, now(), 0, 5, 0, now(), now()
        FROM agent_runs
        WHERE status::text IN ('QUEUED', 'RUNNING', 'WAITING_USER')
        ON CONFLICT (user_id, dedupe_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_durable_jobs_lease", table_name="durable_jobs")
    op.drop_index("ix_durable_jobs_ready_claim", table_name="durable_jobs")
    op.drop_table("durable_jobs")
    postgresql.ENUM(name="durable_job_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="durable_job_kind").drop(op.get_bind(), checkfirst=True)
