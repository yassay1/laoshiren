from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from laoshiren.domain.runtime.entities import (
    MessageRole,
    RunEventType,
    RunStatus,
    RunTrigger,
)


@dataclass(frozen=True, slots=True)
class ThreadDTO:
    id: UUID
    title: str
    active_thing_id: UUID | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class MessageDTO:
    id: UUID
    thread_id: UUID
    role: MessageRole
    content: str
    run_id: UUID | None
    source_ids: list[UUID]
    metadata: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RunDTO:
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
    resume_payload: dict[str, Any] | None
    error_code: str | None
    claim_owner: str | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    attempt_count: int
    version: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime
    stream_url: str
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class RunEventDTO:
    id: UUID
    run_id: UUID
    sequence: int
    event: RunEventType
    occurred_at: datetime
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolExecutionClaimDTO:
    acquired: bool
    cached_result: dict[str, Any] | None = None
    blocked_reason: str | None = None
