"""Expand V2.2 File tables and backfill from legacy sources."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "20260830_0036"
down_revision: str | None = "20260830_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

file_media_kind = postgresql.ENUM(
    "IMAGE",
    "DOCUMENT",
    "AUDIO",
    "VIDEO",
    "OTHER",
    name="file_media_kind",
    create_type=False,
)
file_asset_status = postgresql.ENUM(
    "ACTIVE",
    "DELETED",
    name="file_asset_status",
    create_type=False,
)
file_generation_status = postgresql.ENUM(
    "BUILDING",
    "READY",
    "FAILED",
    "RETIRED",
    name="file_generation_status",
    create_type=False,
)
representation_kind = postgresql.ENUM(
    "TEXT_SPAN",
    "PAGE_TEXT",
    "OCR_BLOCK",
    "TRANSCRIPT_WINDOW",
    "OTHER",
    name="representation_kind",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    file_media_kind.create(bind, checkfirst=True)
    file_asset_status.create(bind, checkfirst=True)
    file_generation_status.create(bind, checkfirst=True)
    representation_kind.create(bind, checkfirst=True)

    op.create_table(
        "files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(length=300), nullable=True),
        sa.Column("validated_mime_type", sa.String(length=200), nullable=False),
        sa.Column("media_kind", file_media_kind, nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("asset_status", file_asset_status, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id", "idempotency_key", name="uq_files_user_idempotency"),
        sa.UniqueConstraint("storage_key", name="uq_files_storage_key"),
    )
    op.create_index("ix_files_owner_created", "files", ["owner_user_id", "created_at"])
    op.create_index("ix_files_owner_deleted", "files", ["owner_user_id", "deleted_at"])

    op.create_table(
        "file_processing_generations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("profile_name", sa.String(length=100), nullable=False),
        sa.Column("parser_version", sa.String(length=100), nullable=False),
        sa.Column("chunk_version", sa.String(length=100), nullable=False),
        sa.Column("embedding_model_version", sa.String(length=100), nullable=True),
        sa.Column("status", file_generation_status, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_file_generations_file_active", "file_processing_generations", ["file_id", "is_active"]
    )
    op.create_index(
        "ix_file_generations_file_created", "file_processing_generations", ["file_id", "created_at"]
    )

    op.create_table(
        "retrieval_segments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("generation_id", sa.Uuid(), nullable=False),
        sa.Column("segment_order", sa.Integer(), nullable=False),
        sa.Column("representation_kind", representation_kind, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("locator", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["generation_id"], ["file_processing_generations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("generation_id", "segment_order", name="uq_retrieval_segments_order"),
    )
    op.create_index(
        "ix_retrieval_segments_file_order", "retrieval_segments", ["file_id", "segment_order"]
    )

    op.create_table(
        "web_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("requested_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("content_type", sa.String(length=200), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieval_method", sa.String(length=100), nullable=False),
        sa.Column("bounded_excerpt", sa.Text(), nullable=True),
        sa.Column("locator", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_web_observations_owner_created", "web_observations", ["owner_user_id", "created_at"]
    )

    op.create_table(
        "message_attachments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("attachment_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "attachment_order", name="uq_message_attachments_order"),
    )
    op.create_index("ix_message_attachments_file", "message_attachments", ["file_id"])

    op.execute(
        """
        INSERT INTO files (
            id, owner_user_id, original_filename, validated_mime_type, media_kind,
            size_bytes, content_sha256, storage_key, asset_status, version,
            idempotency_key, deleted_at, created_at
        )
        SELECT
            s.id,
            s.user_id,
            s.title,
            s.mime_type,
            CASE
                WHEN s.source_type = 'IMAGE' THEN 'IMAGE'
                WHEN s.source_type IN ('PDF', 'WORD', 'PPT') THEN 'DOCUMENT'
                WHEN s.source_type = 'AUDIO' THEN 'AUDIO'
                ELSE 'OTHER'
            END::file_media_kind,
            s.size,
            s.content_hash,
            s.object_key,
            CASE
                WHEN s.deleted_at IS NOT NULL THEN 'DELETED'
                ELSE 'ACTIVE'
            END::file_asset_status,
            1,
            s.idempotency_key,
            s.deleted_at,
            s.created_at
        FROM sources s
        """
    )

    op.execute(
        """
        INSERT INTO file_processing_generations (
            id, file_id, profile_name, parser_version, chunk_version,
            embedding_model_version, status, is_active, created_at, ready_at
        )
        SELECT
            gen_random_uuid(),
            s.id,
            'default',
            COALESCE(s.metadata->>'parser_version', 'legacy'),
            COALESCE(s.metadata->>'chunk_version', 'legacy'),
            s.metadata->>'embedding_model_version',
            'READY'::file_generation_status,
            TRUE,
            COALESCE(s.processed_at, s.created_at),
            COALESCE(s.processed_at, s.created_at)
        FROM sources s
        WHERE s.processing_status = 'READY'
        """
    )

    op.execute(
        """
        INSERT INTO retrieval_segments (
            id, file_id, generation_id, segment_order, representation_kind,
            content, locator, embedding, created_at
        )
        SELECT
            sc.id,
            sc.source_id,
            g.id,
            sc.ordinal,
            CASE
                WHEN sc.page_number IS NOT NULL THEN 'PAGE_TEXT'
                ELSE 'TEXT_SPAN'
            END::representation_kind,
            sc.content,
            jsonb_strip_nulls(
                jsonb_build_object(
                    'char_start', sc.char_start,
                    'char_end', sc.char_end,
                    'page_number', sc.page_number
                ) || COALESCE(sc.metadata, '{}'::jsonb)
            ),
            sc.embedding,
            sc.created_at
        FROM source_chunks sc
        JOIN file_processing_generations g
          ON g.file_id = sc.source_id AND g.is_active = TRUE
        """
    )


def downgrade() -> None:
    op.drop_index("ix_message_attachments_file", table_name="message_attachments")
    op.drop_table("message_attachments")
    op.drop_index("ix_web_observations_owner_created", table_name="web_observations")
    op.drop_table("web_observations")
    op.drop_index("ix_retrieval_segments_file_order", table_name="retrieval_segments")
    op.drop_table("retrieval_segments")
    op.drop_index("ix_file_generations_file_created", table_name="file_processing_generations")
    op.drop_index("ix_file_generations_file_active", table_name="file_processing_generations")
    op.drop_table("file_processing_generations")
    op.drop_index("ix_files_owner_deleted", table_name="files")
    op.drop_index("ix_files_owner_created", table_name="files")
    op.drop_table("files")

    bind = op.get_bind()
    representation_kind.drop(bind, checkfirst=True)
    file_generation_status.drop(bind, checkfirst=True)
    file_asset_status.drop(bind, checkfirst=True)
    file_media_kind.drop(bind, checkfirst=True)
