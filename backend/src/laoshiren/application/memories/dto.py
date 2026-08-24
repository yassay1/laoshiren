from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from laoshiren.domain.memories.entities import MemoryStatus, MemoryType


@dataclass(frozen=True, slots=True)
class MemoryDTO:
    id: UUID
    user_id: UUID
    memory_type: MemoryType
    content: str
    summary: str
    importance: float
    confidence: float
    thing_id: UUID | None
    source_ids: tuple[UUID, ...]
    valid_from: datetime | None
    valid_until: datetime | None
    profile_key: str | None
    supersedes_id: UUID | None
    provenance_run_id: UUID | None
    source_message_ids: tuple[UUID, ...]
    status: MemoryStatus
    version: int
    created_at: datetime
    updated_at: datetime
    last_accessed_at: datetime | None
    replayed: bool = False
