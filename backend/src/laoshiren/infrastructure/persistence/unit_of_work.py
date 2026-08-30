from types import TracebackType
from typing import Self
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from laoshiren.infrastructure.persistence.repositories.automation_notifications import (
    SqlAlchemyAutomationOccurrenceRepository,
    SqlAlchemyNotificationDeliveryRepository,
    SqlAlchemyNotificationIntentRepository,
    SqlAlchemyPushEndpointRepository,
)
from laoshiren.infrastructure.persistence.repositories.automations import (
    SqlAlchemyAttentionRepository,
    SqlAlchemyAutomationRepository,
    SqlAlchemyNotificationOutboxRepository,
)
from laoshiren.infrastructure.persistence.repositories.files import SqlAlchemyFileRepository
from laoshiren.infrastructure.persistence.repositories.identity import (
    SqlAlchemyBusinessSessionRepository,
    SqlAlchemyDeviceRepository,
    SqlAlchemyIdentityUserRepository,
)
from laoshiren.infrastructure.persistence.repositories.memories import SqlAlchemyMemoryRepository
from laoshiren.infrastructure.persistence.repositories.memory_suppressions import (
    SqlAlchemyMemorySuppressionRepository,
)
from laoshiren.infrastructure.persistence.repositories.personal_state import (
    SqlAlchemyAuditRepository,
    SqlAlchemyBlockerRepository,
    SqlAlchemyTaskRepository,
    SqlAlchemyThingContextEntryRepository,
    SqlAlchemyThingDateRepository,
    SqlAlchemyThingRelationRepository,
    SqlAlchemyThingRepository,
)
from laoshiren.infrastructure.persistence.repositories.runtime import (
    SqlAlchemyDurableJobRepository,
    SqlAlchemyMessageRepository,
    SqlAlchemyRunInteractionRepository,
    SqlAlchemyRunRepository,
    SqlAlchemyThreadRepository,
    SqlAlchemyToolExecutionRepository,
)
from laoshiren.infrastructure.persistence.repositories.sources import SqlAlchemySourceRepository


class SqlAlchemyPersonalStateUnitOfWork:
    users: SqlAlchemyIdentityUserRepository
    devices: SqlAlchemyDeviceRepository
    business_sessions: SqlAlchemyBusinessSessionRepository
    things: SqlAlchemyThingRepository
    tasks: SqlAlchemyTaskRepository
    dates: SqlAlchemyThingDateRepository
    context_entries: SqlAlchemyThingContextEntryRepository
    audit: SqlAlchemyAuditRepository
    sources: SqlAlchemySourceRepository
    files: SqlAlchemyFileRepository
    memories: SqlAlchemyMemoryRepository
    memory_suppressions: SqlAlchemyMemorySuppressionRepository
    blockers: SqlAlchemyBlockerRepository
    relations: SqlAlchemyThingRelationRepository
    automations: SqlAlchemyAutomationRepository
    notifications: SqlAlchemyNotificationOutboxRepository
    occurrences: SqlAlchemyAutomationOccurrenceRepository
    notification_intents: SqlAlchemyNotificationIntentRepository
    notification_deliveries: SqlAlchemyNotificationDeliveryRepository
    push_endpoints: SqlAlchemyPushEndpointRepository
    attention: SqlAlchemyAttentionRepository
    threads: SqlAlchemyThreadRepository
    messages: SqlAlchemyMessageRepository
    runs: SqlAlchemyRunRepository
    tool_executions: SqlAlchemyToolExecutionRepository
    durable_jobs: SqlAlchemyDurableJobRepository
    interactions: SqlAlchemyRunInteractionRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.users = SqlAlchemyIdentityUserRepository(self._session)
        self.devices = SqlAlchemyDeviceRepository(self._session)
        self.business_sessions = SqlAlchemyBusinessSessionRepository(self._session)
        self.things = SqlAlchemyThingRepository(self._session)
        self.tasks = SqlAlchemyTaskRepository(self._session)
        self.dates = SqlAlchemyThingDateRepository(self._session)
        self.context_entries = SqlAlchemyThingContextEntryRepository(self._session)
        self.audit = SqlAlchemyAuditRepository(self._session)
        self.sources = SqlAlchemySourceRepository(self._session)
        self.files = SqlAlchemyFileRepository(self._session)
        self.memories = SqlAlchemyMemoryRepository(self._session)
        self.memory_suppressions = SqlAlchemyMemorySuppressionRepository(self._session)
        self.blockers = SqlAlchemyBlockerRepository(self._session)
        self.relations = SqlAlchemyThingRelationRepository(self._session)
        self.automations = SqlAlchemyAutomationRepository(self._session)
        self.notifications = SqlAlchemyNotificationOutboxRepository(self._session)
        self.occurrences = SqlAlchemyAutomationOccurrenceRepository(self._session)
        self.notification_intents = SqlAlchemyNotificationIntentRepository(self._session)
        self.notification_deliveries = SqlAlchemyNotificationDeliveryRepository(self._session)
        self.push_endpoints = SqlAlchemyPushEndpointRepository(self._session)
        self.attention = SqlAlchemyAttentionRepository(self._session)
        self.threads = SqlAlchemyThreadRepository(self._session)
        self.messages = SqlAlchemyMessageRepository(self._session)
        self.runs = SqlAlchemyRunRepository(self._session)
        self.tool_executions = SqlAlchemyToolExecutionRepository(self._session)
        self.durable_jobs = SqlAlchemyDurableJobRepository(self._session)
        self.interactions = SqlAlchemyRunInteractionRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()
        await self._session.close()

    async def commit(self) -> None:
        await self._session.commit()

    async def flush(self) -> None:
        await self._session.flush()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def lock_idempotency(self, *, user_id: UUID, key: str) -> None:
        lock_key = f"{user_id}:{key}"
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": lock_key},
        )
