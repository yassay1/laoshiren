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
from laoshiren.application.runtime.ports import DurableJobRepository
from laoshiren.application.sources.ports import SourceRepository
from laoshiren.domain.automations.entities import (
    AttentionCandidate,
    AttentionFeedbackAction,
    AttentionSubjectType,
    Automation,
    AutomationOccurrence,
    NotificationDelivery,
    NotificationIntent,
    NotificationOutbox,
    PushEndpoint,
)


class AutomationRepository(Protocol):
    async def add(self, automation: Automation) -> None: ...

    async def get(self, *, user_id: UUID, automation_id: UUID) -> Automation | None: ...

    async def get_by_idempotency(self, *, user_id: UUID, key: str) -> Automation | None: ...

    async def list_for_user(self, *, user_id: UUID, limit: int) -> list[Automation]: ...

    async def list_due(self, *, now: datetime, limit: int) -> list[Automation]: ...

    async def update(self, automation: Automation, *, expected_version: int) -> bool: ...

    async def get_operation(self, *, user_id: UUID, key: str) -> tuple[UUID, int] | None: ...

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

    async def complete(self, *, notification: NotificationOutbox, owner: str) -> bool: ...

    async def list_for_user(self, *, user_id: UUID, limit: int) -> list[NotificationOutbox]: ...


class AutomationOccurrenceRepository(Protocol):
    async def add(self, occurrence: AutomationOccurrence) -> bool: ...

    async def get(self, *, occurrence_id: UUID) -> AutomationOccurrence | None: ...

    async def update(self, occurrence: AutomationOccurrence) -> None: ...


class NotificationIntentRepository(Protocol):
    async def add(self, intent: NotificationIntent) -> bool: ...

    async def get_by_dedupe_key(self, *, dedupe_key: str) -> NotificationIntent | None: ...

    async def get(self, *, intent_id: UUID) -> NotificationIntent | None: ...


class NotificationDeliveryRepository(Protocol):
    async def add(self, delivery: NotificationDelivery) -> bool: ...

    async def get(self, *, delivery_id: UUID) -> NotificationDelivery | None: ...

    async def update(self, delivery: NotificationDelivery) -> bool: ...


class PushEndpointRepository(Protocol):
    async def list_eligible(self, *, user_id: UUID) -> list[PushEndpoint]: ...

    async def get(self, *, endpoint_id: UUID) -> PushEndpoint | None: ...

    async def upsert(self, endpoint: PushEndpoint) -> None: ...

    async def invalidate_for_device(self, *, user_id: UUID, device_id: UUID) -> None: ...

    async def invalidate_for_user(self, *, user_id: UUID) -> None: ...


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
    occurrences: AutomationOccurrenceRepository
    notification_intents: NotificationIntentRepository
    notification_deliveries: NotificationDeliveryRepository
    push_endpoints: PushEndpointRepository
    durable_jobs: DurableJobRepository
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


class PushNotificationPort(Protocol):
    async def submit_delivery(
        self,
        *,
        delivery: NotificationDelivery,
        intent: NotificationIntent,
        endpoint: PushEndpoint,
        idempotency_key: str,
    ) -> bool: ...


class NotificationPort(Protocol):
    async def submit(self, notification: NotificationOutbox, *, idempotency_key: str) -> bool: ...


class AutomationRunTrigger(Protocol):
    async def trigger_from_notification(
        self, *, notification: NotificationOutbox
    ) -> UUID | None: ...

    async def trigger_from_occurrence(
        self,
        *,
        user_id: UUID,
        automation_id: UUID,
        thing_id: UUID | None,
        title: str,
        message: str,
        occurrence_key: str,
    ) -> UUID | None: ...
