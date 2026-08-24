from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


def utc_now() -> datetime:
    return datetime.now(UTC)


class MemoryType(StrEnum):
    PROFILE = "PROFILE"
    SEMANTIC = "SEMANTIC"
    EPISODIC = "EPISODIC"


class MemoryStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DELETED = "DELETED"


@dataclass(slots=True)
class Memory:
    user_id: UUID
    memory_type: MemoryType
    content: str
    summary: str
    importance: float
    confidence: float
    idempotency_key: str
    id: UUID = field(default_factory=uuid4)
    thing_id: UUID | None = None
    source_ids: tuple[UUID, ...] = ()
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    embedding: list[float] | None = None
    profile_key: str | None = None
    supersedes_id: UUID | None = None
    provenance_run_id: UUID | None = None
    source_message_ids: tuple[UUID, ...] = ()
    status: MemoryStatus = MemoryStatus.ACTIVE
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    last_accessed_at: datetime | None = None

    def revise(
        self,
        *,
        content: str | None = None,
        summary: str | None = None,
        importance: float | None = None,
        confidence: float | None = None,
    ) -> None:
        if self.status is not MemoryStatus.ACTIVE:
            raise ValueError("Only an active memory can be revised.")
        if content is not None:
            normalized = content.strip()
            if not normalized:
                raise ValueError("Memory content must not be empty.")
            self.content = normalized
        if summary is not None:
            normalized_summary = summary.strip()
            if not normalized_summary:
                raise ValueError("Memory summary must not be empty.")
            self.summary = normalized_summary
        if importance is not None:
            self.importance = importance
        if confidence is not None:
            self.confidence = confidence
        self.updated_at = utc_now()
        self.version += 1

    def supersede(self) -> None:
        if self.status is MemoryStatus.DELETED:
            raise ValueError("A deleted memory cannot be superseded.")
        self.status = MemoryStatus.SUPERSEDED
        self.updated_at = utc_now()
        self.version += 1

    def delete(self) -> None:
        if self.status is MemoryStatus.DELETED:
            return
        self.status = MemoryStatus.DELETED
        self.updated_at = utc_now()
        self.version += 1
