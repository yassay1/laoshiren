from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


def utc_now() -> datetime:
    return datetime.now(UTC)


class FileAssetStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DELETED = "DELETED"


class FileMediaKind(StrEnum):
    IMAGE = "IMAGE"
    DOCUMENT = "DOCUMENT"
    AUDIO = "AUDIO"
    VIDEO = "VIDEO"
    OTHER = "OTHER"


class GenerationStatus(StrEnum):
    BUILDING = "BUILDING"
    READY = "READY"
    FAILED = "FAILED"
    RETIRED = "RETIRED"


class RepresentationKind(StrEnum):
    TEXT_SPAN = "TEXT_SPAN"
    PAGE_TEXT = "PAGE_TEXT"
    OCR_BLOCK = "OCR_BLOCK"
    TRANSCRIPT_WINDOW = "TRANSCRIPT_WINDOW"
    OTHER = "OTHER"


@dataclass(slots=True)
class File:
    owner_user_id: UUID
    validated_mime_type: str
    media_kind: FileMediaKind
    size_bytes: int
    content_sha256: str
    storage_key: str
    idempotency_key: str
    id: UUID = field(default_factory=uuid4)
    original_filename: str | None = None
    asset_status: FileAssetStatus = FileAssetStatus.ACTIVE
    version: int = 1
    deleted_at: datetime | None = None
    purged_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)

    def mark_deleted(self) -> None:
        if self.deleted_at is not None:
            return
        self.deleted_at = utc_now()
        self.asset_status = FileAssetStatus.DELETED


@dataclass(slots=True)
class FileProcessingGeneration:
    file_id: UUID
    profile_name: str
    parser_version: str
    chunk_version: str
    embedding_model_version: str | None
    id: UUID = field(default_factory=uuid4)
    status: GenerationStatus = GenerationStatus.BUILDING
    is_active: bool = False
    created_at: datetime = field(default_factory=utc_now)
    ready_at: datetime | None = None
    retired_at: datetime | None = None

    def mark_ready(self) -> None:
        self.status = GenerationStatus.READY
        self.is_active = True
        self.ready_at = utc_now()

    def retire(self) -> None:
        self.status = GenerationStatus.RETIRED
        self.is_active = False
        self.retired_at = utc_now()


@dataclass(slots=True)
class RetrievalSegment:
    file_id: UUID
    generation_id: UUID
    segment_order: int
    representation_kind: RepresentationKind
    content: str
    id: UUID = field(default_factory=uuid4)
    locator: dict[str, object] = field(default_factory=dict)
    embedding: list[float] | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class WebObservation:
    owner_user_id: UUID
    requested_url: str
    final_url: str
    content_type: str
    observed_at: datetime
    retrieval_method: str
    id: UUID = field(default_factory=uuid4)
    title: str | None = None
    bounded_excerpt: str | None = None
    locator: dict[str, object] = field(default_factory=dict)
    content_hash: str | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class MessageAttachment:
    message_id: UUID
    file_id: UUID
    attachment_order: int
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
