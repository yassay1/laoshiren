from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from laoshiren.application.memories.dto import MemoryDTO
from laoshiren.application.memories.ports import MemoryUnitOfWork
from laoshiren.domain.memories.entities import Memory, MemoryStatus, MemoryType
from laoshiren.domain.personal_state.exceptions import EntityNotFound, VersionConflict

UnitOfWorkFactory = Callable[[], MemoryUnitOfWork]


def to_memory_dto(memory: Memory, *, replayed: bool = False) -> MemoryDTO:
    return MemoryDTO(
        id=memory.id,
        user_id=memory.user_id,
        memory_type=memory.memory_type,
        content=memory.content,
        summary=memory.summary,
        importance=memory.importance,
        confidence=memory.confidence,
        thing_id=memory.thing_id,
        source_ids=memory.source_ids,
        valid_from=memory.valid_from,
        valid_until=memory.valid_until,
        profile_key=memory.profile_key,
        supersedes_id=memory.supersedes_id,
        provenance_run_id=memory.provenance_run_id,
        source_message_ids=memory.source_message_ids,
        status=memory.status,
        version=memory.version,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
        last_accessed_at=memory.last_accessed_at,
        replayed=replayed,
    )


class MemoryApplicationService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def create(
        self,
        *,
        user_id: UUID,
        memory_type: MemoryType,
        content: str,
        summary: str,
        importance: float,
        confidence: float,
        idempotency_key: str,
        thing_id: UUID | None = None,
        source_ids: tuple[UUID, ...] = (),
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        embedding: list[float] | None = None,
        profile_key: str | None = None,
        provenance_run_id: UUID | None = None,
        source_message_ids: tuple[UUID, ...] = (),
    ) -> MemoryDTO:
        normalized_content = content.strip()
        normalized_summary = summary.strip()
        if not normalized_content or not normalized_summary:
            raise ValueError("Memory content and summary must not be empty.")
        if not 0 <= importance <= 1 or not 0 <= confidence <= 1:
            raise ValueError("Memory importance and confidence must be between 0 and 1.")
        if valid_from and valid_until and valid_until <= valid_from:
            raise ValueError("Memory valid_until must be later than valid_from.")
        if embedding is not None and len(embedding) != 1536:
            raise ValueError("Memory embedding must contain exactly 1536 values.")
        normalized_profile_key = profile_key.strip().casefold() if profile_key else None
        if normalized_profile_key and memory_type is not MemoryType.PROFILE:
            raise ValueError("Only PROFILE Memory can define a profile key.")
        if normalized_profile_key and len(normalized_profile_key) > 100:
            raise ValueError("Memory profile key must not exceed 100 characters.")

        async with self._unit_of_work_factory() as unit_of_work:
            if normalized_profile_key:
                await unit_of_work.lock_idempotency(
                    user_id=user_id, key=f"memory-profile:{normalized_profile_key}"
                )
            previous = await unit_of_work.memories.get_by_idempotency(
                user_id=user_id, key=idempotency_key
            )
            if previous is not None:
                return to_memory_dto(previous, replayed=True)
            await unit_of_work.users.ensure_exists(user_id)
            if thing_id is not None and await unit_of_work.things.get(
                user_id=user_id, thing_id=thing_id
            ) is None:
                raise EntityNotFound("Thing was not found.")
            for source_id in source_ids:
                if await unit_of_work.sources.get(user_id=user_id, source_id=source_id) is None:
                    raise EntityNotFound("Source was not found.")
            superseded = None
            if normalized_profile_key:
                superseded = await unit_of_work.memories.get_active_profile(
                    user_id=user_id, profile_key=normalized_profile_key
                )
                if superseded is not None:
                    expected_version = superseded.version
                    superseded.supersede()
                    if not await unit_of_work.memories.update(
                        superseded, expected_version=expected_version
                    ):
                        raise VersionConflict("PROFILE Memory was updated concurrently.")
            memory = Memory(
                user_id=user_id,
                memory_type=memory_type,
                content=normalized_content,
                summary=normalized_summary,
                importance=importance,
                confidence=confidence,
                idempotency_key=idempotency_key,
                thing_id=thing_id,
                source_ids=source_ids,
                valid_from=valid_from,
                valid_until=valid_until,
                embedding=embedding,
                profile_key=normalized_profile_key,
                supersedes_id=superseded.id if superseded is not None else None,
                provenance_run_id=provenance_run_id,
                source_message_ids=source_message_ids,
            )
            await unit_of_work.memories.add(memory)
            await unit_of_work.commit()
            return to_memory_dto(memory)

    async def get(self, *, user_id: UUID, memory_id: UUID) -> MemoryDTO:
        async with self._unit_of_work_factory() as unit_of_work:
            memory = await unit_of_work.memories.get(user_id=user_id, memory_id=memory_id)
            if memory is None:
                raise EntityNotFound("Memory was not found.")
            return to_memory_dto(memory)

    async def search(
        self,
        *,
        user_id: UUID,
        query: str | None = None,
        memory_type: MemoryType | None = None,
        thing_id: UUID | None = None,
        limit: int = 20,
        query_embedding: list[float] | None = None,
    ) -> list[MemoryDTO]:
        if not 1 <= limit <= 50:
            raise ValueError("Memory search limit must be between 1 and 50.")
        if query_embedding is not None and len(query_embedding) != 1536:
            raise ValueError("Query embedding must contain exactly 1536 values.")
        async with self._unit_of_work_factory() as unit_of_work:
            memories = await unit_of_work.memories.search(
                user_id=user_id,
                query=query.strip() if query else None,
                memory_type=memory_type,
                status=MemoryStatus.ACTIVE,
                thing_id=thing_id,
                query_embedding=query_embedding,
                limit=limit,
            )
            return [to_memory_dto(memory) for memory in memories]

    async def update(
        self,
        *,
        user_id: UUID,
        memory_id: UUID,
        expected_version: int,
        content: str | None,
        summary: str | None,
        importance: float | None,
        confidence: float | None,
        idempotency_key: str,
        supersede: bool = False,
        delete: bool = False,
    ) -> MemoryDTO:
        if importance is not None and not 0 <= importance <= 1:
            raise ValueError("Memory importance must be between 0 and 1.")
        if confidence is not None and not 0 <= confidence <= 1:
            raise ValueError("Memory confidence must be between 0 and 1.")
        if supersede and delete:
            raise ValueError("Memory cannot be superseded and deleted together.")
        async with self._unit_of_work_factory() as unit_of_work:
            replay_version = await unit_of_work.memories.get_operation_version(
                user_id=user_id, key=idempotency_key
            )
            if replay_version is not None:
                replay = await unit_of_work.memories.get(user_id=user_id, memory_id=memory_id)
                if replay is None:
                    raise RuntimeError("Idempotent Memory operation points to a missing Memory.")
                return to_memory_dto(replay, replayed=True)
            memory = await unit_of_work.memories.get(user_id=user_id, memory_id=memory_id)
            if memory is None:
                raise EntityNotFound("Memory was not found.")
            if memory.version != expected_version:
                raise VersionConflict("Memory version is stale.")
            if delete:
                memory.delete()
            elif supersede:
                memory.supersede()
            else:
                memory.revise(
                    content=content,
                    summary=summary,
                    importance=importance,
                    confidence=confidence,
                )
            if not await unit_of_work.memories.update(memory, expected_version=expected_version):
                raise VersionConflict("Memory was updated concurrently.")
            await unit_of_work.memories.record_operation(
                user_id=user_id,
                memory_id=memory.id,
                key=idempotency_key,
                target_version=memory.version,
            )
            await unit_of_work.commit()
            return to_memory_dto(memory)
