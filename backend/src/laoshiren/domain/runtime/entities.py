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
    WAITING_FOR_USER = "WAITING_FOR_USER"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RunEventType(StrEnum):
    RUN_QUEUED = "run.queued"
    RUN_STARTED = "run.started"
    ASSISTANT_STARTED = "assistant.started"
    ASSISTANT_COMPLETED = "assistant.completed"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    HITL_REQUESTED = "hitl.requested"
    RUN_WAITING_FOR_USER = "run.waiting_for_user"
    RUN_RESUMED = "run.resumed"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"


class ToolExecutionStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"


class DurableJobKind(StrEnum):
    AGENT_RUN = "AGENT_RUN"
    FILE_PROCESSING = "FILE_PROCESSING"
    FILE_PURGE = "FILE_PURGE"
    MEMORY_FORMATION = "MEMORY_FORMATION"
    AUTOMATION_OCCURRENCE = "AUTOMATION_OCCURRENCE"
    PUSH_DELIVERY = "PUSH_DELIVERY"
    ACCOUNT_DELETION = "ACCOUNT_DELETION"


class DurableJobStatus(StrEnum):
    READY = "READY"
    CLAIMED = "CLAIMED"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RunInteractionStatus(StrEnum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


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
    claim_token: UUID | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    attempt_count: int = 0
    version: int = 1
    event_sequence: int = 0
    active_time_used_ms: int = 0
    active_started_at: datetime | None = None
    terminal_output: dict[str, Any] | None = None
    graph_terminal_at: datetime | None = None
    budget_snapshot: dict[str, Any] = field(default_factory=dict)
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
        self.active_started_at = self.active_started_at or now
        self.current_phase = phase
        self.status_label = label
        self.updated_at = now
        self.version += 1

    def recover_after_crash(self) -> None:
        """Return an abandoned in-flight Run to the durable dispatch queue."""
        if self.status is not RunStatus.RUNNING:
            raise ValueError("Only a running Run can be recovered.")
        now = utc_now()
        self._pause_active_time(now)
        self.status = RunStatus.QUEUED
        self.current_phase = "recovering"
        self.status_label = "Recovering after service restart"
        self._release_claim()
        self.updated_at = now
        self.version += 1

    def wait_for_user(self, *, interrupt_id: UUID, payload: dict[str, Any]) -> None:
        if self.status is not RunStatus.RUNNING:
            raise ValueError("Only a running Run can wait for user input.")
        now = utc_now()
        self._pause_active_time(now)
        self.status = RunStatus.WAITING_FOR_USER
        self.interrupt_id = interrupt_id
        self.interrupt = payload
        self._release_claim()
        self.updated_at = now
        self.version += 1

    def resume(self, *, interrupt_id: UUID, response: dict[str, Any]) -> None:
        if self.status is not RunStatus.WAITING_FOR_USER:
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
        self._pause_active_time(now)
        self.status = RunStatus.COMPLETED
        self.final_message_id = final_message_id
        self.completed_at = now
        self._release_claim()
        self.updated_at = now
        self.version += 1

    def accept_terminal_output(self, output: dict[str, Any]) -> None:
        if self.status is not RunStatus.RUNNING:
            raise ValueError("Only a running Run can accept terminal graph output.")
        if self.terminal_output is not None:
            if self.terminal_output != output:
                raise ValueError("Run already has different terminal graph output.")
            return
        self.terminal_output = dict(output)
        self.graph_terminal_at = utc_now()
        self.updated_at = self.graph_terminal_at
        self.version += 1

    def fail(self, *, error_code: str) -> None:
        if self.status in TERMINAL_RUN_STATUSES:
            raise ValueError("A terminal Run cannot fail again.")
        now = utc_now()
        self._pause_active_time(now)
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
        self._pause_active_time(now)
        self.status = RunStatus.CANCELLED
        self.completed_at = now
        self._release_claim()
        self.updated_at = now
        self.version += 1

    def _release_claim(self) -> None:
        self.claim_owner = None
        self.claim_token = None
        self.lease_expires_at = None
        self.heartbeat_at = None

    def _pause_active_time(self, now: datetime) -> None:
        if self.active_started_at is None:
            return
        elapsed_ms = max(0, int((now - self.active_started_at).total_seconds() * 1000))
        self.active_time_used_ms += elapsed_ms
        self.active_started_at = None


@dataclass(frozen=True, slots=True)
class RunEvent:
    run_id: UUID
    sequence: int
    event_type: RunEventType
    data: dict[str, Any]
    visibility: str = "CLIENT"
    schema_version: int = 1
    id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class RunInteraction:
    user_id: UUID
    run_id: UUID
    interaction_type: str
    request_payload: dict[str, Any]
    id: UUID = field(default_factory=uuid4)
    action_id: str | None = None
    status: RunInteractionStatus = RunInteractionStatus.PENDING
    response_payload: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=utc_now)
    resolved_at: datetime | None = None

    def resolve(self, response: dict[str, Any]) -> None:
        if self.status is RunInteractionStatus.RESOLVED:
            if self.response_payload != response:
                raise ValueError("Interaction was already resolved differently.")
            return
        if self.status is not RunInteractionStatus.PENDING:
            raise ValueError("Only a pending Interaction can be resolved.")
        self.status = RunInteractionStatus.RESOLVED
        self.response_payload = dict(response)
        self.resolved_at = utc_now()


@dataclass(slots=True)
class ToolExecution:
    run_id: UUID
    action_id: str
    tool_name: str
    arguments_hash: str
    status: ToolExecutionStatus
    claim_owner: str
    claim_token: UUID
    lease_expires_at: datetime
    replay_safe: bool = True
    idempotency_key: str | None = None
    id: UUID = field(default_factory=uuid4)
    result: dict[str, Any] | None = None
    receipt: dict[str, Any] | None = None
    error_code: str | None = None
    provider_idempotency_key: str | None = None
    provider_request_id: str | None = None
    attempt_count: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class DurableJob:
    user_id: UUID
    kind: DurableJobKind
    dedupe_key: str
    payload: dict[str, Any]
    id: UUID = field(default_factory=uuid4)
    status: DurableJobStatus = DurableJobStatus.READY
    priority: int = 0
    available_at: datetime = field(default_factory=utc_now)
    delivery_attempt: int = 0
    max_delivery_attempts: int = 5
    claimed_by: str | None = None
    claim_epoch: int = 0
    lease_until: datetime | None = None
    last_error_code: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.dedupe_key.strip():
            raise ValueError("Durable Job dedupe key must not be empty.")
        if self.available_at.tzinfo is None:
            raise ValueError("Durable Job availability must include timezone information.")
        if self.max_delivery_attempts < 1:
            raise ValueError("Durable Job must allow at least one delivery attempt.")

    def claim(self, *, owner: str, lease_until: datetime) -> None:
        if self.status is not DurableJobStatus.READY:
            raise ValueError("Only a ready Durable Job can be claimed.")
        if not owner.strip() or lease_until.tzinfo is None:
            raise ValueError("Durable Job claim requires an owner and aware lease.")
        self.status = DurableJobStatus.CLAIMED
        self.claimed_by = owner
        self.claim_epoch += 1
        self.delivery_attempt += 1
        self.lease_until = lease_until
        self.updated_at = utc_now()

    def settle(self, status: DurableJobStatus) -> None:
        if status not in {
            DurableJobStatus.PAUSED,
            DurableJobStatus.COMPLETED,
            DurableJobStatus.FAILED,
            DurableJobStatus.CANCELLED,
        }:
            raise ValueError("Durable Job can only settle to a non-running status.")
        self.status = status
        self.claimed_by = None
        self.lease_until = None
        self.updated_at = utc_now()
