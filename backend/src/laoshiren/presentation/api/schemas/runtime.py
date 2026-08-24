from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from laoshiren.application.runtime.dto import MessageDTO, RunDTO, ThreadDTO
from laoshiren.domain.runtime.entities import MessageRole, RunStatus, RunTrigger


class CreateThreadRequest(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=300)
    active_thing_id: UUID | None = None


class ThreadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    active_thing_id: UUID | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    replayed: bool

    @classmethod
    def from_dto(cls, value: ThreadDTO) -> "ThreadResponse":
        return cls.model_validate(value)


class RunMessageRequest(BaseModel):
    type: Literal["text"] = "text"
    content: str = Field(min_length=1, max_length=20000)


class CreateRunRequest(BaseModel):
    thread_id: UUID
    message: RunMessageRequest
    source_ids: list[UUID] = Field(default_factory=list, max_length=20)


class ResumeRunRequest(BaseModel):
    interrupt_id: UUID
    response: dict[str, Any]
    expected_version: int = Field(ge=1)


class CancelRunRequest(BaseModel):
    expected_version: int = Field(ge=1)


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    thread_id: UUID
    trigger: RunTrigger
    input_message_id: UUID | None
    status: RunStatus
    current_phase: str | None
    status_label: str | None
    final_message_id: UUID | None
    interrupt_id: UUID | None
    interrupt: dict[str, Any] | None
    error_code: str | None
    version: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime
    stream_url: str
    replayed: bool

    @classmethod
    def from_dto(cls, value: RunDTO) -> "RunResponse":
        return cls.model_validate(value)


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    thread_id: UUID
    role: MessageRole
    content: str
    run_id: UUID | None
    source_ids: list[UUID]
    metadata: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_dto(cls, value: MessageDTO) -> "MessageResponse":
        return cls.model_validate(value)
