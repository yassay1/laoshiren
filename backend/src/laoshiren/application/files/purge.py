"""Logical delete enqueue and physical purge for deleted Files."""

from datetime import UTC, datetime
from uuid import UUID

from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.domain.runtime.entities import DurableJob, DurableJobKind


async def enqueue_file_purge(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    file_id: UUID,
    object_key: str,
) -> None:
    dedupe_key = f"file-purge:{file_id}"
    existing = await uow.durable_jobs.get_by_dedupe_key(user_id=user_id, dedupe_key=dedupe_key)
    if existing is not None:
        return
    await uow.durable_jobs.add(
        DurableJob(
            user_id=user_id,
            kind=DurableJobKind.FILE_PURGE,
            dedupe_key=dedupe_key,
            payload={"file_id": str(file_id), "object_key": object_key},
            available_at=datetime.now(UTC),
        )
    )


async def apply_physical_purge(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    file_id: UUID,
) -> str | None:
    file = await uow.files.get_including_deleted(user_id=user_id, file_id=file_id)
    if file is None:
        return None
    if file.purged_at is not None:
        return file.storage_key
    await uow.files.mark_purged(user_id=user_id, file_id=file_id)
    await uow.files.purge_segments_for_file(file_id=file_id)
    return file.storage_key
