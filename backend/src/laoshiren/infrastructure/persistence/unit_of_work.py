from types import TracebackType
from typing import Self
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from laoshiren.infrastructure.persistence.repositories.automations import (
    SqlAlchemyAttentionRepository,
    SqlAlchemyAutomationRepository,
    SqlAlchemyNotificationOutboxRepository,
)
from laoshiren.infrastructure.persistence.repositories.memories import SqlAlchemyMemoryRepository
from laoshiren.infrastructure.persistence.repositories.personal_state import (
    SqlAlchemyAuditRepository,
    SqlAlchemyBlockerRepository,
    SqlAlchemyTaskRepository,
    SqlAlchemyThingDateRepository,
    SqlAlchemyThingRelationRepository,
    SqlAlchemyThingRepository,
    SqlAlchemyUserRepository,
)
from laoshiren.infrastructure.persistence.repositories.runtime import (
    SqlAlchemyMessageRepository,
    SqlAlchemyRunRepository,
    SqlAlchemyThreadRepository,
    SqlAlchemyToolExecutionRepository,
)
from laoshiren.infrastructure.persistence.repositories.sources import SqlAlchemySourceRepository


class SqlAlchemyPersonalStateUnitOfWork:
    users: SqlAlchemyUserRepository
    things: SqlAlchemyThingRepository
    tasks: SqlAlchemyTaskRepository
    dates: SqlAlchemyThingDateRepository
    audit: SqlAlchemyAuditRepository
    sources: SqlAlchemySourceRepository
    memories: SqlAlchemyMemoryRepository
    blockers: SqlAlchemyBlockerRepository
    relations: SqlAlchemyThingRelationRepository
    automations: SqlAlchemyAutomationRepository
    notifications: SqlAlchemyNotificationOutboxRepository
    attention: SqlAlchemyAttentionRepository
    threads: SqlAlchemyThreadRepository
    messages: SqlAlchemyMessageRepository
    runs: SqlAlchemyRunRepository
    tool_executions: SqlAlchemyToolExecutionRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.users = SqlAlchemyUserRepository(self._session)
        self.things = SqlAlchemyThingRepository(self._session)
        self.tasks = SqlAlchemyTaskRepository(self._session)
        self.dates = SqlAlchemyThingDateRepository(self._session)
        self.audit = SqlAlchemyAuditRepository(self._session)
        self.sources = SqlAlchemySourceRepository(self._session)
        self.memories = SqlAlchemyMemoryRepository(self._session)
        self.blockers = SqlAlchemyBlockerRepository(self._session)
        self.relations = SqlAlchemyThingRelationRepository(self._session)
        self.automations = SqlAlchemyAutomationRepository(self._session)
        self.notifications = SqlAlchemyNotificationOutboxRepository(self._session)
        self.attention = SqlAlchemyAttentionRepository(self._session)
        self.threads = SqlAlchemyThreadRepository(self._session)
        self.messages = SqlAlchemyMessageRepository(self._session)
        self.runs = SqlAlchemyRunRepository(self._session)
        self.tool_executions = SqlAlchemyToolExecutionRepository(self._session)
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
