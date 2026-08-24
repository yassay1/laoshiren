from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from laoshiren.application.memories.dto import MemoryDTO
from laoshiren.domain.memories.entities import MemoryStatus, MemoryType


class CreateMemoryRequest(BaseModel):
    memory_type: MemoryType
    content: str = Field(min_length=1, max_length=10000)
    summary: str = Field(min_length=1, max_length=1000)
    importance: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    thing_id: UUID | None = None
    source_ids: tuple[UUID, ...] = ()
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class UpdateMemoryRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=10000)
    summary: str | None = Field(default=None, min_length=1, max_length=1000)
    importance: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    supersede: bool = False
    expected_version: int = Field(ge=1)


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    status: MemoryStatus
    version: int
    created_at: datetime
    updated_at: datetime
    last_accessed_at: datetime | None
    replayed: bool

    @classmethod
    def from_dto(cls, value: MemoryDTO) -> "MemoryResponse":
        return cls.model_validate(value)
