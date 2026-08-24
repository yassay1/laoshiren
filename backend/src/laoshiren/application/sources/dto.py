from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from laoshiren.domain.sources.entities import ProcessingStatus, SourceOrigin, SourceType


@dataclass(frozen=True, slots=True)
class SourceDTO:
    id: UUID
    user_id: UUID
    source_type: SourceType
    origin: SourceOrigin
    title: str
    mime_type: str
    size: int
    content_hash: str
    processing_status: ProcessingStatus
    extracted_text: str | None
    processing_error: str | None
    processed_at: datetime | None
    captured_at: datetime | None
    metadata: dict[str, object]
    created_at: datetime
    replayed: bool = False
