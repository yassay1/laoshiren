from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


def utc_now() -> datetime:
    return datetime.now(UTC)


class MessageRole(StrEnum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    SYSTEM_EVENT = "SYSTEM_EVENT"


class RunTrigger(StrEnum):
    USER_MESSAGE = "USER_MESSAGE"
    AUTOMATION = "AUTOMATION"
    SYSTEM_EVENT = "SYSTEM_EVENT"


class RunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_USER = "WAITING_USER"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RunEventType(StrEnum):
    RUN_STARTED = "run.started"
    ASSISTANT_DELTA = "assistant.delta"
    ASSISTANT_MESSAGE = "assistant.message"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    STATUS_UPDATED = "status.updated"
    INTERRUPT_REQUIRED = "interrupt.required"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    HEARTBEAT = "heartbeat"


class ToolExecutionStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


TERMINAL_RUN_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
}


@dataclass(slots=True)
class Thread:
    user_id: UUID
    title: str
    idempotency_key: str
    id: UUID = field(default_factory=uuid4)
    active_thing_id: UUID | None = None
    archived_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def archive(self) -> None:
        if self.archived_at is None:
            self.archived_at = utc_now()
            self.updated_at = self.archived_at


@dataclass(slots=True)
class Message:
    user_id: UUID
    thread_id: UUID
    role: MessageRole
    content: str
    id: UUID = field(default_factory=uuid4)
    run_id: UUID | None = None
    source_ids: list[UUID] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class AgentRun:
    user_id: UUID
    thread_id: UUID
    trigger: RunTrigger
    idempotency_key: str
    id: UUID = field(default_factory=uuid4)
    input_message_id: UUID | None = None
    status: RunStatus = RunStatus.QUEUED
    current_phase: str | None = None
    status_label: str | None = None
    final_message_id: UUID | None = None
    interrupt_id: UUID | None = None
    interrupt: dict[str, Any] | None = None
    resume_payload: dict[str, Any] | None = None
    error_code: str | None = None
    claim_owner: str | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    attempt_count: int = 0
    version: int = 1
    event_sequence: int = 0
    created_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime = field(default_factory=utc_now)

    def start(self, *, phase: str | None = None, label: str | None = None) -> None:
        if self.status is not RunStatus.QUEUED:
            raise ValueError("Only a queued Run can start.")
        now = utc_now()
        self.status = RunStatus.RUNNING
        self.started_at = self.started_at or now
        self.current_phase = phase
        self.status_label = label
        self.updated_at = now
        self.version += 1

    def recover_after_crash(self) -> None:
        """Return an abandoned in-flight Run to the durable dispatch queue."""
        if self.status is not RunStatus.RUNNING:
            raise ValueError("Only a running Run can be recovered.")
        self.status = RunStatus.QUEUED
        self.current_phase = "recovering"
        self.status_label = "Recovering after service restart"
        self._release_claim()
        self.updated_at = utc_now()
        self.version += 1

    def wait_for_user(self, *, interrupt_id: UUID, payload: dict[str, Any]) -> None:
        if self.status is not RunStatus.RUNNING:
            raise ValueError("Only a running Run can wait for user input.")
        self.status = RunStatus.WAITING_USER
        self.interrupt_id = interrupt_id
        self.interrupt = payload
        self._release_claim()
        self.updated_at = utc_now()
        self.version += 1

    def resume(self, *, interrupt_id: UUID, response: dict[str, Any]) -> None:
        if self.status is not RunStatus.WAITING_USER:
            raise ValueError("Only a Run waiting for user input can resume.")
        if self.interrupt_id != interrupt_id:
            raise ValueError("Interrupt id does not match the active interrupt.")
        self.status = RunStatus.QUEUED
        self.interrupt_id = None
        self.interrupt = None
        self.resume_payload = response
        self.current_phase = "resuming"
        self.status_label = "正在继续处理"
        self.updated_at = utc_now()
        self.version += 1

    def complete(self, *, final_message_id: UUID) -> None:
        if self.status is not RunStatus.RUNNING:
            raise ValueError("Only a running Run can complete.")
        now = utc_now()
        self.status = RunStatus.COMPLETED
        self.final_message_id = final_message_id
        self.completed_at = now
        self._release_claim()
        self.updated_at = now
        self.version += 1

    def fail(self, *, error_code: str) -> None:
        if self.status in TERMINAL_RUN_STATUSES:
            raise ValueError("A terminal Run cannot fail again.")
        now = utc_now()
        self.status = RunStatus.FAILED
        self.error_code = error_code
        self.completed_at = now
        self._release_claim()
        self.updated_at = now
        self.version += 1

    def cancel(self) -> None:
        if self.status in TERMINAL_RUN_STATUSES:
            raise ValueError("A terminal Run cannot be cancelled.")
        now = utc_now()
        self.status = RunStatus.CANCELLED
        self.completed_at = now
        self._release_claim()
        self.updated_at = now
        self.version += 1

    def _release_claim(self) -> None:
        self.claim_owner = None
        self.lease_expires_at = None
        self.heartbeat_at = None


@dataclass(frozen=True, slots=True)
class RunEvent:
    run_id: UUID
    sequence: int
    event_type: RunEventType
    data: dict[str, Any]
    id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class ToolExecution:
    run_id: UUID
    action_id: str
    tool_name: str
    arguments_hash: str
    status: ToolExecutionStatus
    claim_owner: str
    lease_expires_at: datetime
    id: UUID = field(default_factory=uuid4)
    result: dict[str, Any] | None = None
    attempt_count: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
