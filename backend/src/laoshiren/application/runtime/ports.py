from types import TracebackType
from typing import Any, Protocol, Self
from uuid import UUID

from laoshiren.application.personal_state.ports import ThingRepository, UserRepository
from laoshiren.application.sources.ports import SourceRepository
from laoshiren.domain.runtime.entities import (
    AgentRun,
    Message,
    RunEvent,
    RunEventType,
    Thread,
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
    async def update(self, run: AgentRun, *, expected_version: int) -> bool: ...
    async def get_operation(
        self, *, user_id: UUID, key: str
    ) -> tuple[UUID, int] | None: ...
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
        self, *, user_id: UUID, run_id: UUID, after_event_id: UUID | None, limit: int
    ) -> list[RunEvent]: ...


class RunDispatcher(Protocol):
    async def dispatch(self, *, user_id: UUID, run_id: UUID) -> None: ...


class RuntimeUnitOfWork(Protocol):
    users: UserRepository
    things: ThingRepository
    sources: SourceRepository
    threads: ThreadRepository
    messages: MessageRepository
    runs: RunRepository

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
