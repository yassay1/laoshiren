from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


def utc_now() -> datetime:
    return datetime.now(UTC)


class SourceType(StrEnum):
    IMAGE = "IMAGE"
    PDF = "PDF"
    WORD = "WORD"
    PPT = "PPT"
    AUDIO = "AUDIO"
    OTHER = "OTHER"


class SourceOrigin(StrEnum):
    CHAT = "CHAT"
    SHARE = "SHARE"
    UPLOAD = "UPLOAD"
    AUTOMATION = "AUTOMATION"
    SYSTEM = "SYSTEM"


class ProcessingStatus(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"


class SourceRelationType(StrEnum):
    PRIMARY = "PRIMARY"
    SUPPORTING = "SUPPORTING"
    REFERENCE = "REFERENCE"
    EVIDENCE = "EVIDENCE"
    OTHER = "OTHER"


@dataclass(slots=True)
class Source:
    user_id: UUID
    source_type: SourceType
    origin: SourceOrigin
    title: str
    mime_type: str
    object_key: str
    content_hash: str
    size: int
    idempotency_key: str
    id: UUID = field(default_factory=uuid4)
    external_url: str | None = None
    captured_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    processing_status: ProcessingStatus = ProcessingStatus.PENDING
    extracted_text: str | None = None
    processing_error: str | None = None
    processed_at: datetime | None = None
    processing_claim_owner: str | None = None
    processing_lease_expires_at: datetime | None = None
    processing_heartbeat_at: datetime | None = None
    processing_attempt_count: int = 0
    next_processing_attempt_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)

    def mark_ready(self, *, extracted_text: str) -> None:
        self.extracted_text = extracted_text.strip()
        self.processing_status = ProcessingStatus.READY
        self.processing_error = None
        self.processed_at = utc_now()
        self.processing_claim_owner = None
        self.processing_lease_expires_at = None
        self.processing_heartbeat_at = None
        self.next_processing_attempt_at = None

    def mark_failed(self, *, error_code: str) -> None:
        self.processing_status = ProcessingStatus.FAILED
        self.processing_error = error_code
        self.processed_at = utc_now()
        self.processing_claim_owner = None
        self.processing_lease_expires_at = None
        self.processing_heartbeat_at = None
        self.next_processing_attempt_at = None


@dataclass(slots=True)
class ThingSource:
    thing_id: UUID
    source_id: UUID
    relation_type: SourceRelationType
    relevance: float = 1.0
    created_at: datetime = field(default_factory=utc_now)
