from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from laoshiren.domain.files.entities import (
    FileAssetStatus,
    FileMediaKind,
    GenerationStatus,
    RepresentationKind,
)
from laoshiren.infrastructure.persistence.orm.base import Base


class FileORM(Base):
    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "idempotency_key", name="uq_files_user_idempotency"),
        Index("ix_files_owner_created", "owner_user_id", "created_at"),
        Index("ix_files_owner_deleted", "owner_user_id", "deleted_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    original_filename: Mapped[str | None] = mapped_column(String(300))
    validated_mime_type: Mapped[str] = mapped_column(String(200))
    media_kind: Mapped[FileMediaKind] = mapped_column(Enum(FileMediaKind, name="file_media_kind"))
    size_bytes: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    asset_status: Mapped[FileAssetStatus] = mapped_column(
        Enum(FileAssetStatus, name="file_asset_status")
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FileProcessingGenerationORM(Base):
    __tablename__ = "file_processing_generations"
    __table_args__ = (
        Index("ix_file_generations_file_active", "file_id", "is_active"),
        Index("ix_file_generations_file_created", "file_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    file_id: Mapped[UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    profile_name: Mapped[str] = mapped_column(String(100))
    parser_version: Mapped[str] = mapped_column(String(100))
    chunk_version: Mapped[str] = mapped_column(String(100))
    embedding_model_version: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[GenerationStatus] = mapped_column(
        Enum(GenerationStatus, name="file_generation_status")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RetrievalSegmentORM(Base):
    __tablename__ = "retrieval_segments"
    __table_args__ = (
        UniqueConstraint("generation_id", "segment_order", name="uq_retrieval_segments_order"),
        Index("ix_retrieval_segments_file_order", "file_id", "segment_order"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    file_id: Mapped[UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    generation_id: Mapped[UUID] = mapped_column(
        ForeignKey("file_processing_generations.id", ondelete="CASCADE")
    )
    segment_order: Mapped[int] = mapped_column(Integer)
    representation_kind: Mapped[RepresentationKind] = mapped_column(
        Enum(RepresentationKind, name="representation_kind")
    )
    content: Mapped[str] = mapped_column(Text)
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebObservationORM(Base):
    __tablename__ = "web_observations"
    __table_args__ = (Index("ix_web_observations_owner_created", "owner_user_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    requested_url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(200))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retrieval_method: Mapped[str] = mapped_column(String(100))
    bounded_excerpt: Mapped[str | None] = mapped_column(Text)
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MessageAttachmentORM(Base):
    __tablename__ = "message_attachments"
    __table_args__ = (
        UniqueConstraint("message_id", "attachment_order", name="uq_message_attachments_order"),
        Index("ix_message_attachments_file", "file_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    file_id: Mapped[UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    attachment_order: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
