"""Memory mutations that run inside a shared Unit of Work (no commit)."""

from datetime import datetime
from uuid import UUID

from laoshiren.application.memories.candidate import profile_key_for
from laoshiren.application.memories.fingerprint import memory_content_fingerprint
from laoshiren.application.memories.reconciliation import (
    duplicates_current_state,
    load_state_fact_snapshot,
)
from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.application.personal_state.write_ops import WriteOutcome
from laoshiren.domain.memories.entities import Memory, MemoryType
from laoshiren.domain.personal_state.exceptions import EntityNotFound, VersionConflict


async def apply_create_memory(
    uow: PersonalStateUnitOfWork,
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
    reconcile_state: bool = False,
) -> WriteOutcome:
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
    if normalized_profile_key:
        await uow.lock_idempotency(user_id=user_id, key=f"memory-profile:{normalized_profile_key}")
    await uow.lock_idempotency(user_id=user_id, key="memory-reconcile")
    fingerprint = memory_content_fingerprint(normalized_content)
    if reconcile_state and await uow.memory_suppressions.is_suppressed(
        user_id=user_id, content_fingerprint=fingerprint
    ):
        return WriteOutcome(
            code="MEMORY_SUPPRESSED",
            message="Memory content is suppressed.",
            data={"replayed": False},
            mutation_refs=(),
            replayed=False,
        )
    if reconcile_state:
        state_snapshot = await load_state_fact_snapshot(uow, user_id=user_id)
        if duplicates_current_state(content=normalized_content, snapshot=state_snapshot):
            return WriteOutcome(
                code="MEMORY_STATE_DUPLICATE",
                message="Memory duplicates current Personal State.",
                data={"replayed": False},
                mutation_refs=(),
                replayed=False,
            )
    previous = await uow.memories.get_by_idempotency(user_id=user_id, key=idempotency_key)
    if previous is not None:
        return WriteOutcome(
            code="MEMORY_REMEMBERED",
            message="Memory remembered.",
            data={
                "id": str(previous.id),
                "type": previous.memory_type.value,
                "replayed": True,
            },
            mutation_refs=(),
            replayed=True,
        )
    await uow.users.ensure_exists(user_id)
    if (
        thing_id is not None
        and await uow.things.get(user_id=user_id, thing_id=thing_id) is None
    ):
        raise EntityNotFound("Thing was not found.")
    for source_id in source_ids:
        if await uow.sources.get(user_id=user_id, source_id=source_id) is None:
            raise EntityNotFound("Source was not found.")
    superseded = None
    if normalized_profile_key:
        superseded = await uow.memories.get_active_profile(
            user_id=user_id, profile_key=normalized_profile_key
        )
        if superseded is not None:
            expected_version = superseded.version
            superseded.supersede()
            if not await uow.memories.update(superseded, expected_version=expected_version):
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
    await uow.memories.add(memory)
    await uow.memory_suppressions.clear(user_id=user_id, content_fingerprint=fingerprint)
    await uow.flush()
    return WriteOutcome(
        code="MEMORY_REMEMBERED",
        message="Memory remembered.",
        data={"id": str(memory.id), "type": memory.memory_type.value, "replayed": False},
        mutation_refs=(),
    )


async def apply_explicit_remember(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    run_id: UUID,
    content: str,
    memory_type: MemoryType,
    idempotency_key: str,
    thing_id: UUID | None = None,
) -> WriteOutcome:
    profile_key = (
        profile_key_for(content) if memory_type is MemoryType.PROFILE else None
    )
    return await apply_create_memory(
        uow,
        user_id=user_id,
        memory_type=memory_type,
        content=content,
        summary=content[:200],
        importance=0.6,
        confidence=0.7,
        idempotency_key=idempotency_key,
        thing_id=thing_id,
        profile_key=profile_key,
        provenance_run_id=run_id,
    )


async def apply_forget_memory(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    memory_id: UUID,
    expected_version: int,
    idempotency_key: str,
) -> WriteOutcome:
    replay_version = await uow.memories.get_operation_version(user_id=user_id, key=idempotency_key)
    if replay_version is not None:
        replay = await uow.memories.get(user_id=user_id, memory_id=memory_id)
        if replay is None:
            raise RuntimeError("Idempotent Memory operation points to a missing Memory.")
        return WriteOutcome(
            code="MEMORY_FORGOTTEN",
            message="Memory forgotten.",
            data={"id": str(replay.id), "replayed": True},
            mutation_refs=(),
            replayed=True,
        )
    memory = await uow.memories.get(user_id=user_id, memory_id=memory_id)
    if memory is None:
        raise EntityNotFound("Memory was not found.")
    if memory.version != expected_version:
        raise VersionConflict("Memory version is stale.")
    memory.delete()
    if not await uow.memories.update(memory, expected_version=expected_version):
        raise VersionConflict("Memory was updated concurrently.")
    await uow.memory_suppressions.record(
        user_id=user_id,
        content_fingerprint=memory_content_fingerprint(memory.content),
        memory_id=memory.id,
    )
    await uow.memories.record_operation(
        user_id=user_id,
        memory_id=memory.id,
        key=idempotency_key,
        target_version=memory.version,
    )
    return WriteOutcome(
        code="MEMORY_FORGOTTEN",
        message="Memory forgotten.",
        data={"id": str(memory.id), "replayed": False},
        mutation_refs=(),
    )
