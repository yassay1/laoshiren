from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from laoshiren.application.personal_state.ports import ThingRepository, UserRepository
from laoshiren.application.sources.ports import SourceRepository
from laoshiren.domain.memories.entities import Memory, MemoryStatus, MemoryType


class MemorySuppressionRepository(Protocol):
    async def is_suppressed(self, *, user_id: UUID, content_fingerprint: str) -> bool: ...

    async def record(
        self,
        *,
        user_id: UUID,
        content_fingerprint: str,
        memory_id: UUID | None,
    ) -> None: ...

    async def clear(self, *, user_id: UUID, content_fingerprint: str) -> None: ...


class MemoryRepository(Protocol):
    async def add(self, memory: Memory) -> None: ...

    async def get(self, *, user_id: UUID, memory_id: UUID) -> Memory | None: ...

    async def get_by_idempotency(self, *, user_id: UUID, key: str) -> Memory | None: ...

    async def get_active_profile(self, *, user_id: UUID, profile_key: str) -> Memory | None: ...

    async def search(
        self,
        *,
        user_id: UUID,
        query: str | None,
        memory_type: MemoryType | None,
        status: MemoryStatus,
        thing_id: UUID | None,
        query_embedding: list[float] | None,
        limit: int,
    ) -> list[Memory]: ...

    async def update(self, memory: Memory, *, expected_version: int) -> bool: ...

    async def get_operation_version(self, *, user_id: UUID, key: str) -> int | None: ...

    async def record_operation(
        self, *, user_id: UUID, memory_id: UUID, key: str, target_version: int
    ) -> None: ...


class MemoryUnitOfWork(Protocol):
    users: UserRepository
    things: ThingRepository
    sources: SourceRepository
    memories: MemoryRepository
    memory_suppressions: MemorySuppressionRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def lock_idempotency(self, *, user_id: UUID, key: str) -> None: ...
