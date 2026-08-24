from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from laoshiren.domain.automations.entities import (
    AutomationStatus,
    NotificationStatus,
)
from laoshiren.domain.runtime.entities import RunStatus
from laoshiren.domain.sources.entities import ProcessingStatus
from laoshiren.infrastructure.persistence.orm.personal_state import (
    AgentRunORM,
    AutomationORM,
    NotificationOutboxORM,
    SourceORM,
)


class SqlAlchemyOperationalStatusAdapter:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def count_backlogs(self, *, now: datetime) -> dict[str, int]:
        counters = {
            "runs_queued": select(func.count()).select_from(AgentRunORM).where(
                AgentRunORM.status == RunStatus.QUEUED
            ),
            "runs_expired": select(func.count()).select_from(AgentRunORM).where(
                AgentRunORM.status == RunStatus.RUNNING,
                AgentRunORM.lease_expires_at <= now,
            ),
            "sources_due": select(func.count()).select_from(SourceORM).where(
                or_(
                    and_(
                        SourceORM.processing_status == ProcessingStatus.PENDING,
                        or_(
                            SourceORM.processing_lease_expires_at.is_(None),
                            SourceORM.processing_lease_expires_at <= now,
                        ),
                    ),
                    and_(
                        SourceORM.processing_status == ProcessingStatus.FAILED,
                        SourceORM.next_processing_attempt_at <= now,
                    ),
                )
            ),
            "automations_due": select(func.count()).select_from(AutomationORM).where(
                AutomationORM.status == AutomationStatus.ACTIVE,
                AutomationORM.next_trigger_at <= now,
            ),
            "notifications_due": select(func.count())
            .select_from(NotificationOutboxORM)
            .where(
                or_(
                    and_(
                        NotificationOutboxORM.status == NotificationStatus.PENDING,
                        or_(
                            NotificationOutboxORM.lease_expires_at.is_(None),
                            NotificationOutboxORM.lease_expires_at <= now,
                        ),
                    ),
                    and_(
                        NotificationOutboxORM.status == NotificationStatus.FAILED,
                        NotificationOutboxORM.next_attempt_at <= now,
                    ),
                )
            ),
        }
        statement = select(
            *[query.scalar_subquery().label(name) for name, query in counters.items()]
        )
        async with self._session_factory() as session:
            row = (await session.execute(statement)).one()
        return {name: int(row[index]) for index, name in enumerate(counters)}
