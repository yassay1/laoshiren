from datetime import datetime
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from laoshiren.application.personal_state.ports import (
    BlockerRepository,
    TaskRepository,
    ThingRepository,
    UserRepository,
)
from laoshiren.application.sources.ports import SourceRepository
from laoshiren.domain.automations.entities import (
    AttentionCandidate,
    AttentionFeedbackAction,
    AttentionSubjectType,
    Automation,
    NotificationOutbox,
)


class AutomationRepository(Protocol):
    async def add(self, automation: Automation) -> None: ...

    async def get(self, *, user_id: UUID, automation_id: UUID) -> Automation | None: ...

    async def get_by_idempotency(self, *, user_id: UUID, key: str) -> Automation | None: ...

    async def list_for_user(self, *, user_id: UUID, limit: int) -> list[Automation]: ...

    async def list_due(self, *, now: datetime, limit: int) -> list[Automation]: ...

    async def update(self, automation: Automation, *, expected_version: int) -> bool: ...

    async def get_operation(
        self, *, user_id: UUID, key: str
    ) -> tuple[UUID, int] | None: ...

    async def record_operation(
        self, *, user_id: UUID, automation_id: UUID, key: str, target_version: int
    ) -> None: ...


class NotificationOutboxRepository(Protocol):
    async def add(self, notification: NotificationOutbox) -> bool: ...

    async def claim_next(
        self,
        *,
        owner: str,
        now: datetime,
        lease_expires_at: datetime,
        max_attempts: int,
    ) -> NotificationOutbox | None: ...

    async def complete(
        self, *, notification: NotificationOutbox, owner: str
    ) -> bool: ...

    async def list_for_user(
        self, *, user_id: UUID, limit: int
    ) -> list[NotificationOutbox]: ...


class AttentionRepository(Protocol):
    async def get_candidates(
        self, *, user_id: UUID, now: datetime, due_soon_hours: int, limit: int
    ) -> list[AttentionCandidate]: ...

    async def record_feedback(
        self,
        *,
        user_id: UUID,
        subject_type: AttentionSubjectType,
        subject_id: UUID,
        action: AttentionFeedbackAction,
        now: datetime,
        dismissed_until: datetime | None,
    ) -> None: ...


class AutomationUnitOfWork(Protocol):
    users: UserRepository
    things: ThingRepository
    tasks: TaskRepository
    blockers: BlockerRepository
    sources: SourceRepository
    automations: AutomationRepository
    notifications: NotificationOutboxRepository
    attention: AttentionRepository

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


class NotificationPort(Protocol):
    async def submit(
        self, notification: NotificationOutbox, *, idempotency_key: str
    ) -> bool: ...
