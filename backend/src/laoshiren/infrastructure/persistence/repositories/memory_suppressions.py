from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from laoshiren.infrastructure.persistence.orm.personal_state import MemorySuppressionORM


class SqlAlchemyMemorySuppressionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_suppressed(self, *, user_id: UUID, content_fingerprint: str) -> bool:
        value = await self._session.scalar(
            select(MemorySuppressionORM.id).where(
                MemorySuppressionORM.user_id == user_id,
                MemorySuppressionORM.content_fingerprint == content_fingerprint,
            )
        )
        return value is not None

    async def record(
        self,
        *,
        user_id: UUID,
        content_fingerprint: str,
        memory_id: UUID | None,
    ) -> None:
        existing = await self._session.scalar(
            select(MemorySuppressionORM.id).where(
                MemorySuppressionORM.user_id == user_id,
                MemorySuppressionORM.content_fingerprint == content_fingerprint,
            )
        )
        if existing is not None:
            return
        self._session.add(
            MemorySuppressionORM(
                id=uuid4(),
                user_id=user_id,
                content_fingerprint=content_fingerprint,
                memory_id=memory_id,
            )
        )

    async def clear(self, *, user_id: UUID, content_fingerprint: str) -> None:
        model = await self._session.scalar(
            select(MemorySuppressionORM).where(
                MemorySuppressionORM.user_id == user_id,
                MemorySuppressionORM.content_fingerprint == content_fingerprint,
            )
        )
        if model is not None:
            await self._session.delete(model)
