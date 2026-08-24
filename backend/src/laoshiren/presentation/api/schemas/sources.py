from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from laoshiren.application.sources.dto import SourceDTO
from laoshiren.domain.sources.entities import (
    ProcessingStatus,
    SourceOrigin,
    SourceRelationType,
    SourceType,
)


class SourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    source_type: SourceType
    origin: SourceOrigin
    title: str
    mime_type: str
    size: int
    content_hash: str
    processing_status: ProcessingStatus
    captured_at: datetime | None
    metadata: dict[str, object]
    created_at: datetime
    replayed: bool

    @classmethod
    def from_dto(cls, value: SourceDTO) -> "SourceResponse":
        return cls.model_validate(value)


class LinkSourceRequest(BaseModel):
    relation_type: SourceRelationType = SourceRelationType.REFERENCE
    relevance: float = Field(default=1.0, ge=0, le=1)
    reason: str = Field(min_length=1, max_length=500)


class LinkSourceResponse(BaseModel):
    created: bool
