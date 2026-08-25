from datetime import datetime
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from laoshiren.application.sources.ports import SourceRepository
from laoshiren.domain.personal_state.entities import (
    Blocker,
    StateMutation,
    Task,
    Thing,
    ThingDate,
    ThingRelation,
    TimelineEvent,
)
from laoshiren.domain.personal_state.value_objects import ThingStatus


class UserRepository(Protocol):
    async def ensure_exists(self, user_id: UUID) -> None: ...


class ThingRepository(Protocol):
    async def add(self, thing: Thing) -> None: ...

    async def get(self, *, user_id: UUID, thing_id: UUID) -> Thing | None: ...

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        status: ThingStatus | None,
        query: str | None,
        cursor: UUID | None,
        limit: int,
    ) -> list[Thing]: ...

    async def update(self, thing: Thing, *, expected_version: int) -> bool: ...

    async def list_upcoming(
        self, *, user_id: UUID, now: datetime, window_end: datetime, limit: int
    ) -> list[Thing]: ...

    async def list_active(self, *, user_id: UUID, limit: int) -> list[Thing]: ...

    async def list_recent(self, *, user_id: UUID, limit: int) -> list[Thing]: ...


class ThingDateRepository(Protocol):
    async def add(self, thing_date: ThingDate) -> None: ...

    async def unset_primary(self, *, thing_id: UUID, kind: str) -> None: ...

    async def list_for_thing(
        self, *, user_id: UUID, thing_id: UUID, limit: int
    ) -> list[ThingDate]: ...

    async def get(self, *, user_id: UUID, date_id: UUID) -> ThingDate | None: ...

    async def update(self, thing_date: ThingDate, *, expected_version: int) -> bool: ...


class TaskRepository(Protocol):
    async def add(self, task: Task) -> None: ...

    async def get(self, *, user_id: UUID, task_id: UUID) -> Task | None: ...

    async def list_for_thing(self, *, user_id: UUID, thing_id: UUID) -> list[Task]: ...

    async def update(self, task: Task, *, expected_version: int) -> bool: ...

    async def count_open(self, *, user_id: UUID, thing_ids: list[UUID]) -> dict[UUID, int]: ...


class AuditRepository(Protocol):
    async def get_mutation(
        self, *, user_id: UUID, idempotency_key: str
    ) -> StateMutation | None: ...

    async def add_mutation(self, mutation: StateMutation) -> None: ...

    async def add_timeline_event(self, event: TimelineEvent) -> None: ...

    async def list_timeline(
        self,
        *,
        user_id: UUID,
        thing_id: UUID,
        event_type: str | None,
        limit: int,
    ) -> list[TimelineEvent]: ...

    async def list_mutations(
        self, *, user_id: UUID, thing_id: UUID, limit: int
    ) -> list[StateMutation]: ...


class BlockerRepository(Protocol):
    async def add(self, blocker: Blocker) -> None: ...

    async def get(self, *, user_id: UUID, blocker_id: UUID) -> Blocker | None: ...

    async def list_for_thing(self, *, user_id: UUID, thing_id: UUID) -> list[Blocker]: ...

    async def update(self, blocker: Blocker, *, expected_version: int) -> bool: ...

    async def list_open(
        self, *, user_id: UUID, limit: int
    ) -> list[tuple[Blocker, str]]: ...


class ThingRelationRepository(Protocol):
    async def add(self, relation: ThingRelation) -> bool: ...

    async def list_for_thing(
        self, *, user_id: UUID, thing_id: UUID
    ) -> list[ThingRelation]: ...


class PersonalStateUnitOfWork(Protocol):
    users: UserRepository
    things: ThingRepository
    tasks: TaskRepository
    dates: ThingDateRepository
    audit: AuditRepository
    sources: SourceRepository
    blockers: BlockerRepository
    relations: ThingRelationRepository

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
