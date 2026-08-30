"""Add durable first-class Run interactions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260830_0020"
down_revision: str | None = "20260830_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    status = postgresql.ENUM(
        "PENDING",
        "RESOLVED",
        "CANCELLED",
        name="run_interaction_status",
        create_type=False,
    )
    status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "run_interactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.String(length=200)),
        sa.Column("interaction_type", sa.String(length=50), nullable=False),
        sa.Column("status", status, nullable=False),
        sa.Column("request_payload", postgresql.JSONB(), nullable=False),
        sa.Column("response_payload", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_run_interactions_run_status",
        "run_interactions",
        ["run_id", "status"],
    )
    op.create_index(
        "uq_run_interactions_one_pending",
        "run_interactions",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.execute(
        """
        INSERT INTO run_interactions (
            id, user_id, run_id, interaction_type, status,
            request_payload, created_at
        )
        SELECT interrupt_id, user_id, id,
               COALESCE(interrupt->>'type', 'CONFIRMATION'),
               'PENDING', interrupt, updated_at
        FROM agent_runs
        WHERE status::text = 'WAITING_USER'
          AND interrupt_id IS NOT NULL
          AND interrupt IS NOT NULL
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("uq_run_interactions_one_pending", table_name="run_interactions")
    op.drop_index("ix_run_interactions_run_status", table_name="run_interactions")
    op.drop_table("run_interactions")
    postgresql.ENUM(name="run_interaction_status").drop(op.get_bind(), checkfirst=True)
