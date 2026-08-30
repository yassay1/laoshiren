from datetime import datetime
from types import TracebackType
from typing import Any, Protocol, Self
from uuid import UUID

from laoshiren.application.personal_state.ports import (
    AuditRepository,
    ThingRepository,
    UserRepository,
)
from laoshiren.application.runtime.dto import (
    CheckpointSnapshotDTO,
    ContextAssemblyDTO,
    ContextAssemblyRequestDTO,
    EphemeralFrameDTO,
)
from laoshiren.application.sources.ports import SourceRepository
from laoshiren.domain.runtime.entities import (
    AgentRun,
    DurableJob,
    DurableJobKind,
    DurableJobStatus,
    Message,
    RunEvent,
    RunEventType,
    RunInteraction,
    Thread,
    ToolExecution,
)


class ThreadRepository(Protocol):
    async def add(self, thread: Thread) -> None: ...
    async def get(self, *, user_id: UUID, thread_id: UUID) -> Thread | None: ...
    async def get_by_idempotency(self, *, user_id: UUID, key: str) -> Thread | None: ...
    async def list_for_user(
        self, *, user_id: UUID, limit: int, include_archived: bool
    ) -> list[Thread]: ...
    async def archive(self, thread: Thread) -> None: ...


class MessageRepository(Protocol):
    async def add(self, message: Message) -> None: ...
    async def get(self, *, user_id: UUID, message_id: UUID) -> Message | None: ...
    async def list_for_thread(
        self, *, user_id: UUID, thread_id: UUID, limit: int
    ) -> list[Message]: ...


class RunRepository(Protocol):
    async def add(self, run: AgentRun) -> None: ...
    async def get(self, *, user_id: UUID, run_id: UUID) -> AgentRun | None: ...
    async def get_by_idempotency(self, *, user_id: UUID, key: str) -> AgentRun | None: ...
    async def list_recoverable(self, *, now: datetime, limit: int) -> list[AgentRun]: ...
    async def claim(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        owner: str,
        claim_token: UUID,
        now: datetime,
        lease_expires_at: datetime,
    ) -> AgentRun | None: ...
    async def renew_lease(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        owner: str,
        claim_token: UUID,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool: ...
    async def update(self, run: AgentRun, *, expected_version: int) -> bool: ...
    async def get_operation(self, *, user_id: UUID, key: str) -> tuple[UUID, int] | None: ...
    async def record_operation(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        key: str,
        operation: str,
        target_version: int,
    ) -> None: ...
    async def append_event(
        self, *, run_id: UUID, event_type: RunEventType, data: dict[str, Any]
    ) -> RunEvent: ...
    async def list_events(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        after_event_id: UUID | None,
        after_sequence: int | None,
        limit: int,
    ) -> list[RunEvent]: ...


class ToolExecutionRepository(Protocol):
    async def get(self, *, run_id: UUID, action_id: str) -> ToolExecution | None: ...
    async def list_in_progress(self, *, run_id: UUID) -> list[ToolExecution]: ...
    async def add_if_absent(self, execution: ToolExecution) -> bool: ...
    async def takeover_if_expired(
        self,
        execution: ToolExecution,
        *,
        now: datetime,
        owner: str,
        claim_token: UUID,
        lease_expires_at: datetime,
    ) -> bool: ...
    async def complete(
        self,
        *,
        run_id: UUID,
        action_id: str,
        owner: str,
        claim_token: UUID,
        result: dict[str, Any],
        succeeded: bool,
        now: datetime,
    ) -> bool: ...
    async def mark_unknown_if_expired(self, *, execution_id: UUID, now: datetime) -> bool: ...
    async def reconcile_unknown(
        self,
        *,
        execution_id: UUID,
        result: dict[str, Any],
        succeeded: bool,
        provider_request_id: str | None,
        now: datetime,
    ) -> bool: ...


class DurableJobRepository(Protocol):
    async def add(self, job: DurableJob) -> None: ...
    async def get_by_dedupe_key(self, *, user_id: UUID, dedupe_key: str) -> DurableJob | None: ...
    async def claim_ready(
        self,
        *,
        kind: DurableJobKind,
        owner: str,
        now: datetime,
        lease_until: datetime,
        limit: int,
    ) -> list[DurableJob]: ...
    async def settle(
        self,
        *,
        job_id: UUID,
        owner: str,
        claim_epoch: int,
        status: DurableJobStatus,
        now: datetime,
        error_code: str | None = None,
    ) -> bool: ...
    async def renew(
        self,
        *,
        job_id: UUID,
        owner: str,
        claim_epoch: int,
        lease_until: datetime,
        now: datetime,
    ) -> bool: ...
    async def requeue_expired(self, *, now: datetime) -> int: ...
    async def resume(self, *, user_id: UUID, dedupe_key: str, now: datetime) -> bool: ...
    async def cancel(self, *, user_id: UUID, dedupe_key: str, now: datetime) -> bool: ...


class RunInteractionRepository(Protocol):
    async def add(self, interaction: RunInteraction) -> None: ...
    async def get(
        self, *, user_id: UUID, run_id: UUID, interaction_id: UUID
    ) -> RunInteraction | None: ...
    async def resolve(self, interaction: RunInteraction) -> None: ...


class RunDispatcher(Protocol):
    async def dispatch(self, *, user_id: UUID, run_id: UUID) -> None: ...


class RuntimeWakeup(Protocol):
    async def publish(self, *, run_id: UUID, latest_sequence: int) -> None: ...
    async def publish_frame(self, frame: EphemeralFrameDTO) -> None: ...
    async def subscribe(self, *, run_id: UUID) -> "RuntimeLiveSubscription | None": ...
    async def wait(self, *, run_id: UUID, timeout_seconds: float) -> EphemeralFrameDTO | None: ...
    async def close(self) -> None: ...


class RuntimeLiveSubscription(Protocol):
    """One live-stream subscription; durable events remain PostgreSQL-backed."""

    async def wait(self, *, timeout_seconds: float) -> EphemeralFrameDTO | None: ...
    async def close(self) -> None: ...


class CheckpointInspector(Protocol):
    async def inspect(self, *, run_id: UUID) -> CheckpointSnapshotDTO: ...


class ModelContextAssembler(Protocol):
    """Application boundary for per-invocation, current-reality context."""

    async def assemble(self, *, request: ContextAssemblyRequestDTO) -> ContextAssemblyDTO: ...


class RuntimeUnitOfWork(Protocol):
    users: UserRepository
    things: ThingRepository
    audit: AuditRepository
    sources: SourceRepository
    threads: ThreadRepository
    messages: MessageRepository
    runs: RunRepository
    tool_executions: ToolExecutionRepository
    durable_jobs: DurableJobRepository
    interactions: RunInteractionRepository

    async def lock_idempotency(self, *, user_id: UUID, key: str) -> None: ...

    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
    async def commit(self) -> None: ...
    async def flush(self) -> None: ...
    async def rollback(self) -> None: ...
