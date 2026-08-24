"""Add sources and many-to-many Thing relations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0003"
down_revision: str | None = "20260823_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    source_type = postgresql.ENUM(
        "IMAGE",
        "PDF",
        "WORD",
        "PPT",
        "AUDIO",
        "OTHER",
        name="source_type",
        create_type=False,
    )
    source_origin = postgresql.ENUM(
        "CHAT",
        "SHARE",
        "UPLOAD",
        "AUTOMATION",
        "SYSTEM",
        name="source_origin",
        create_type=False,
    )
    processing_status = postgresql.ENUM(
        "PENDING",
        "READY",
        "FAILED",
        name="source_processing_status",
        create_type=False,
    )
    relation_type = postgresql.ENUM(
        "PRIMARY",
        "SUPPORTING",
        "REFERENCE",
        "EVIDENCE",
        "OTHER",
        name="source_relation_type",
        create_type=False,
    )
    bind = op.get_bind()
    source_type.create(bind, checkfirst=True)
    source_origin.create(bind, checkfirst=True)
    processing_status.create(bind, checkfirst=True)
    relation_type.create(bind, checkfirst=True)

    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", source_type, nullable=False),
        sa.Column("origin", source_origin, nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("mime_type", sa.String(length=200), nullable=False),
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("processing_status", processing_status, nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_sources_user_idempotency"),
    )
    op.create_index("ix_sources_user_created", "sources", ["user_id", "created_at"])
    op.create_table(
        "thing_sources",
        sa.Column("thing_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("relation_type", relation_type, nullable=False),
        sa.Column("relevance", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.ForeignKeyConstraint(["thing_id"], ["things.id"]),
        sa.PrimaryKeyConstraint("thing_id", "source_id"),
    )


def downgrade() -> None:
    op.drop_table("thing_sources")
    op.drop_index("ix_sources_user_created", table_name="sources")
    op.drop_table("sources")
    for enum_name in (
        "source_relation_type",
        "source_processing_status",
        "source_origin",
        "source_type",
    ):
        postgresql.ENUM(name=enum_name).drop(op.get_bind(), checkfirst=True)
