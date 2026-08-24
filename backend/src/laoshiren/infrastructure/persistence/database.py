from typing import cast

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from laoshiren.application.automations.ports import AutomationUnitOfWork
from laoshiren.application.memories.ports import MemoryUnitOfWork
from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.application.runtime.ports import RuntimeUnitOfWork
from laoshiren.infrastructure.persistence.unit_of_work import (
    SqlAlchemyPersonalStateUnitOfWork,
)


class Database:
    def __init__(self, url: str) -> None:
        self.engine = create_async_engine(url, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    def personal_state_unit_of_work(self) -> PersonalStateUnitOfWork:
        unit_of_work = SqlAlchemyPersonalStateUnitOfWork(self.session_factory)
        return cast(PersonalStateUnitOfWork, unit_of_work)

    def memory_unit_of_work(self) -> MemoryUnitOfWork:
        unit_of_work = SqlAlchemyPersonalStateUnitOfWork(self.session_factory)
        return cast(MemoryUnitOfWork, unit_of_work)

    def automation_unit_of_work(self) -> AutomationUnitOfWork:
        unit_of_work = SqlAlchemyPersonalStateUnitOfWork(self.session_factory)
        return cast(AutomationUnitOfWork, unit_of_work)

    def runtime_unit_of_work(self) -> RuntimeUnitOfWork:
        unit_of_work = SqlAlchemyPersonalStateUnitOfWork(self.session_factory)
        return cast(RuntimeUnitOfWork, unit_of_work)

    async def dispose(self) -> None:
        await self.engine.dispose()
