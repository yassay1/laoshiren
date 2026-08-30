"""Add Long-term Memory with pgvector support."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0004"
down_revision: str | None = "20260824_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    memory_type = postgresql.ENUM(
        "PROFILE", "SEMANTIC", "EPISODIC", name="memory_type", create_type=False
    )
    memory_status = postgresql.ENUM(
        "ACTIVE", "SUPERSEDED", "DELETED", name="memory_status", create_type=False
    )
    bind = op.get_bind()
    memory_type.create(bind, checkfirst=True)
    memory_status.create(bind, checkfirst=True)
    op.create_table(
        "long_term_memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("memory_type", memory_type, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("thing_id", sa.Uuid(), nullable=True),
        sa.Column(
            "source_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("status", memory_status, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("importance >= 0 AND importance <= 1", name="ck_memory_importance"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_memory_confidence"),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
            name="ck_memory_valid_range",
        ),
        sa.ForeignKeyConstraint(["thing_id"], ["things.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_memories_user_idempotency"),
    )
    op.create_index(
        "ix_memories_user_status_type",
        "long_term_memories",
        ["user_id", "status", "memory_type"],
    )
    op.create_index("ix_memories_thing_status", "long_term_memories", ["thing_id", "status"])
    op.create_table(
        "memory_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["memory_id"], ["long_term_memories.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_memory_operations_key"),
    )


def downgrade() -> None:
    op.drop_table("memory_operations")
    op.drop_index("ix_memories_thing_status", table_name="long_term_memories")
    op.drop_index("ix_memories_user_status_type", table_name="long_term_memories")
    op.drop_table("long_term_memories")
    postgresql.ENUM(name="memory_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="memory_type").drop(op.get_bind(), checkfirst=True)
