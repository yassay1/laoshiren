from typing import Any, cast
from uuid import UUID

from sqlalchemy import insert, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from laoshiren.domain.memories.entities import Memory, MemoryStatus, MemoryType
from laoshiren.infrastructure.persistence.orm.personal_state import MemoryOperationORM, MemoryORM


def memory_to_domain(model: MemoryORM) -> Memory:
    return Memory(
        id=model.id,
        user_id=model.user_id,
        memory_type=model.memory_type,
        content=model.content,
        summary=model.summary,
        importance=model.importance,
        confidence=model.confidence,
        thing_id=model.thing_id,
        source_ids=tuple(model.source_ids),
        valid_from=model.valid_from,
        valid_until=model.valid_until,
        embedding=list(model.embedding) if model.embedding is not None else None,
        profile_key=model.profile_key,
        supersedes_id=model.supersedes_id,
        provenance_run_id=model.provenance_run_id,
        source_message_ids=tuple(model.source_message_ids),
        status=model.status,
        version=model.version,
        idempotency_key=model.idempotency_key,
        created_at=model.created_at,
        updated_at=model.updated_at,
        last_accessed_at=model.last_accessed_at,
    )


class SqlAlchemyMemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, memory: Memory) -> None:
        self._session.add(
            MemoryORM(
                id=memory.id,
                user_id=memory.user_id,
                memory_type=memory.memory_type,
                content=memory.content,
                summary=memory.summary,
                importance=memory.importance,
                confidence=memory.confidence,
                thing_id=memory.thing_id,
                source_ids=list(memory.source_ids),
                valid_from=memory.valid_from,
                valid_until=memory.valid_until,
                embedding=memory.embedding,
                profile_key=memory.profile_key,
                supersedes_id=memory.supersedes_id,
                provenance_run_id=memory.provenance_run_id,
                source_message_ids=list(memory.source_message_ids),
                status=memory.status,
                version=memory.version,
                idempotency_key=memory.idempotency_key,
                created_at=memory.created_at,
                updated_at=memory.updated_at,
                last_accessed_at=memory.last_accessed_at,
            )
        )

    async def get(self, *, user_id: UUID, memory_id: UUID) -> Memory | None:
        model = await self._session.scalar(
            select(MemoryORM).where(MemoryORM.id == memory_id, MemoryORM.user_id == user_id)
        )
        return memory_to_domain(model) if model is not None else None

    async def get_by_idempotency(self, *, user_id: UUID, key: str) -> Memory | None:
        model = await self._session.scalar(
            select(MemoryORM).where(MemoryORM.user_id == user_id, MemoryORM.idempotency_key == key)
        )
        return memory_to_domain(model) if model is not None else None

    async def get_active_profile(self, *, user_id: UUID, profile_key: str) -> Memory | None:
        model = await self._session.scalar(
            select(MemoryORM).where(
                MemoryORM.user_id == user_id,
                MemoryORM.memory_type == MemoryType.PROFILE,
                MemoryORM.status == MemoryStatus.ACTIVE,
                MemoryORM.profile_key == profile_key,
            )
        )
        return memory_to_domain(model) if model is not None else None

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
    ) -> list[Memory]:
        statement = select(MemoryORM).where(
            MemoryORM.user_id == user_id, MemoryORM.status == status
        )
        if memory_type is not None:
            statement = statement.where(MemoryORM.memory_type == memory_type)
        if thing_id is not None:
            statement = statement.where(MemoryORM.thing_id == thing_id)
        if query:
            pattern = f"%{query}%"
            statement = statement.where(
                or_(MemoryORM.content.ilike(pattern), MemoryORM.summary.ilike(pattern))
            )
        if query_embedding is not None:
            statement = statement.where(MemoryORM.embedding.is_not(None)).order_by(
                MemoryORM.embedding.cosine_distance(query_embedding),
                MemoryORM.importance.desc(),
            )
        elif memory_type is MemoryType.PROFILE and query is None:
            # Profile memories represent current user reality.  Importance is
            # not a safe proxy for freshness here: an older, highly important
            # profile must not crowd the current active version out of the
            # bounded context window.
            statement = statement.order_by(MemoryORM.updated_at.desc(), MemoryORM.id.desc())
        else:
            statement = statement.order_by(
                MemoryORM.importance.desc(), MemoryORM.updated_at.desc(), MemoryORM.id.desc()
            )
        models = (await self._session.scalars(statement.limit(limit))).all()
        return [memory_to_domain(model) for model in models]

    async def update(self, memory: Memory, *, expected_version: int) -> bool:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(MemoryORM)
                .where(MemoryORM.id == memory.id, MemoryORM.version == expected_version)
                .values(
                    content=memory.content,
                    summary=memory.summary,
                    importance=memory.importance,
                    confidence=memory.confidence,
                    profile_key=memory.profile_key,
                    supersedes_id=memory.supersedes_id,
                    status=memory.status,
                    version=memory.version,
                    updated_at=memory.updated_at,
                )
            ),
        )
        return result.rowcount == 1

    async def get_operation_version(self, *, user_id: UUID, key: str) -> int | None:
        value: int | None = await self._session.scalar(
            select(MemoryOperationORM.target_version).where(
                MemoryOperationORM.user_id == user_id,
                MemoryOperationORM.idempotency_key == key,
            )
        )
        return value

    async def record_operation(
        self, *, user_id: UUID, memory_id: UUID, key: str, target_version: int
    ) -> None:
        await self._session.execute(
            insert(MemoryOperationORM).values(
                user_id=user_id,
                memory_id=memory_id,
                idempotency_key=key,
                target_version=target_version,
            )
        )
