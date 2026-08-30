"""Source/File mutations that run inside a shared Unit of Work (no commit)."""

from uuid import UUID

from laoshiren.application.files import sync as file_sync
from laoshiren.application.files.purge import enqueue_file_purge
from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.application.personal_state.write_ops import WriteOutcome
from laoshiren.domain.personal_state.entities import StateMutation
from laoshiren.domain.personal_state.exceptions import EntityNotFound


async def apply_delete_file(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    source_id: UUID,
    action_id: str,
    idempotency_key: str,
    reason: str,
) -> WriteOutcome:
    previous = await uow.audit.get_mutation(user_id=user_id, idempotency_key=idempotency_key)
    if previous is not None:
        replay = await uow.sources.get_including_deleted(user_id=user_id, source_id=source_id)
        if replay is None:
            raise RuntimeError("Idempotent file delete points to a missing Source.")
        return WriteOutcome(
            code="FILE_DELETED",
            message="File deleted.",
            data={
                "mutation_id": str(previous.id),
                "file_id": str(source_id),
                "replayed": True,
            },
            mutation_refs=(str(previous.id),),
            mutation_id=previous.id,
            replayed=True,
        )
    source = await uow.sources.get(user_id=user_id, source_id=source_id)
    if source is None:
        raise EntityNotFound("Source was not found.")
    object_key = source.object_key
    deleted = await uow.sources.mark_deleted(user_id=user_id, source_id=source_id)
    if deleted is None:
        raise EntityNotFound("Source was not found.")
    await uow.sources.purge_chunks(source_id=source_id)
    await file_sync.mirror_source_delete(uow, user_id=user_id, file_id=source_id)
    await enqueue_file_purge(
        uow,
        user_id=user_id,
        file_id=source_id,
        object_key=object_key,
    )
    mutation = StateMutation(
        user_id=user_id,
        thing_id=None,
        action_id=action_id,
        mutation_type="FILE_DELETED",
        target_type="SOURCE",
        target_id=source_id,
        after={
            "deleted_at": deleted.deleted_at.isoformat() if deleted.deleted_at else None,
        },
        reason=reason,
        idempotency_key=idempotency_key,
    )
    await uow.audit.add_mutation(mutation)
    await uow.flush()
    return WriteOutcome(
        code="FILE_DELETED",
        message="File deleted.",
        data={
            "mutation_id": str(mutation.id),
            "file_id": str(source_id),
            "purge_enqueued": True,
            "replayed": False,
        },
        mutation_refs=(str(mutation.id),),
        mutation_id=mutation.id,
    )
