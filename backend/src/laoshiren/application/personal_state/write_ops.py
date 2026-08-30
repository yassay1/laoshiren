"""Personal State mutations that run inside a shared Unit of Work (no commit)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from laoshiren.application.files.evidence import file_evidence_ref
from laoshiren.application.personal_state.dto import MutationResultDTO
from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.domain.personal_state.entities import (
    Blocker,
    StateMutation,
    Task,
    Thing,
    ThingContextEntry,
    ThingDate,
    TimelineEvent,
    utc_now,
)
from laoshiren.domain.personal_state.exceptions import EntityNotFound, VersionConflict
from laoshiren.domain.personal_state.value_objects import (
    BlockerSeverity,
    DateCertainty,
    DatePrecision,
    TaskStatus,
    ThingDateType,
)


@dataclass(frozen=True, slots=True)
class WriteOutcome:
    code: str
    message: str
    data: dict[str, Any]
    mutation_refs: tuple[str, ...]
    mutation_id: UUID | None = None
    replayed: bool = False


def _replay_from_mutation(mutation: StateMutation) -> WriteOutcome:
    version = mutation.after.get("version")
    if not isinstance(version, int):
        version = mutation.after.get("date_version")
    if not isinstance(version, int):
        version = mutation.after.get("thing_version", 1)
    data = {
        "mutation_id": str(mutation.id),
        "target_id": str(mutation.target_id),
        "version": version,
        "replayed": True,
    }
    return WriteOutcome(
        code=mutation.mutation_type,
        message="Mutation replayed.",
        data=data,
        mutation_refs=(str(mutation.id),),
        mutation_id=mutation.id,
        replayed=True,
    )


async def apply_change_archive(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    thing_id: UUID,
    expected_version: int,
    action_id: str,
    idempotency_key: str,
    reason: str,
    run_id: UUID | None,
    archive: bool,
) -> WriteOutcome:
    previous = await uow.audit.get_mutation(user_id=user_id, idempotency_key=idempotency_key)
    if previous is not None:
        outcome = _replay_from_mutation(previous)
        code = "THING_ARCHIVED" if archive else "THING_RESTORED"
        return WriteOutcome(
            code=code,
            message=outcome.message,
            data={
                "mutation_id": str(previous.id),
                "thing_id": str(previous.target_id),
                "version": outcome.data["version"],
                "replayed": True,
            },
            mutation_refs=outcome.mutation_refs,
            mutation_id=previous.id,
            replayed=True,
        )
    thing = await uow.things.get(user_id=user_id, thing_id=thing_id)
    if thing is None:
        raise EntityNotFound("Thing was not found.")
    if thing.version != expected_version:
        raise VersionConflict("Thing version is stale.")
    before: dict[str, object] = {
        "archived_at": thing.archived_at.isoformat() if thing.archived_at else None,
        "version": thing.version,
    }
    if archive:
        thing.archive()
        mutation_type = "THING_ARCHIVED"
        event_type = "THING_ARCHIVED"
        title = f"归档事务：{thing.name}"
        code = "THING_ARCHIVED"
        msg = "Thing archived."
    else:
        thing.unarchive()
        mutation_type = "THING_UNARCHIVED"
        event_type = "THING_UNARCHIVED"
        title = f"恢复事务：{thing.name}"
        code = "THING_RESTORED"
        msg = "Thing restored."
    if not await uow.things.update(thing, expected_version=expected_version):
        raise VersionConflict("Thing was updated concurrently.")
    mutation = StateMutation(
        user_id=user_id,
        thing_id=thing.id,
        run_id=run_id,
        action_id=action_id,
        mutation_type=mutation_type,
        target_type="THING",
        target_id=thing.id,
        before=before,
        after={
            "archived_at": thing.archived_at.isoformat() if thing.archived_at else None,
            "version": thing.version,
        },
        reason=reason,
        idempotency_key=idempotency_key,
    )
    await uow.audit.add_mutation(mutation)
    await uow.flush()
    await uow.audit.add_timeline_event(
        TimelineEvent(
            user_id=user_id,
            thing_id=thing.id,
            event_type=event_type,
            title=title,
            occurred_at=thing.updated_at,
            mutation_id=mutation.id,
        )
    )
    data = {
        "mutation_id": str(mutation.id),
        "thing_id": str(thing.id),
        "version": thing.version,
        "replayed": False,
    }
    return WriteOutcome(
        code=code,
        message=msg,
        data=data,
        mutation_refs=(str(mutation.id),),
        mutation_id=mutation.id,
    )


async def apply_delete_thing(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    thing_id: UUID,
    expected_version: int,
    action_id: str,
    idempotency_key: str,
    reason: str,
    run_id: UUID | None,
) -> WriteOutcome:
    previous = await uow.audit.get_mutation(user_id=user_id, idempotency_key=idempotency_key)
    if previous is not None:
        version = previous.after.get("version")
        if not isinstance(version, int):
            raise RuntimeError("Stored delete mutation is missing its target version.")
        return WriteOutcome(
            code="THING_DELETED",
            message="Thing deleted.",
            data={
                "mutation_id": str(previous.id),
                "thing_id": str(previous.target_id),
                "version": version,
                "replayed": True,
            },
            mutation_refs=(str(previous.id),),
            mutation_id=previous.id,
            replayed=True,
        )
    thing = await uow.things.get_including_deleted(user_id=user_id, thing_id=thing_id)
    if thing is None or thing.deleted_at is not None:
        raise EntityNotFound("Thing was not found.")
    if thing.version != expected_version:
        raise VersionConflict("Thing version is stale.")
    before: dict[str, object] = {"deleted_at": None, "version": thing.version}
    await uow.things.detach_tasks(thing_id=thing.id)
    await uow.things.delete_owned_components(thing_id=thing.id)
    thing.delete()
    if not await uow.things.update(thing, expected_version=expected_version):
        raise VersionConflict("Thing was updated concurrently.")
    mutation = StateMutation(
        user_id=user_id,
        thing_id=thing.id,
        run_id=run_id,
        action_id=action_id,
        mutation_type="THING_DELETED",
        target_type="THING",
        target_id=thing.id,
        before=before,
        after={
            "deleted_at": thing.deleted_at.isoformat() if thing.deleted_at else None,
            "version": thing.version,
        },
        reason=reason,
        idempotency_key=idempotency_key,
    )
    await uow.audit.add_mutation(mutation)
    await uow.flush()
    await uow.audit.add_timeline_event(
        TimelineEvent(
            user_id=user_id,
            thing_id=thing.id,
            event_type="THING_DELETED",
            title=f"删除事务：{thing.name}",
            occurred_at=thing.updated_at,
            mutation_id=mutation.id,
        )
    )
    return WriteOutcome(
        code="THING_DELETED",
        message="Thing deleted.",
        data={
            "mutation_id": str(mutation.id),
            "thing_id": str(thing.id),
            "version": thing.version,
            "replayed": False,
        },
        mutation_refs=(str(mutation.id),),
        mutation_id=mutation.id,
    )


async def apply_create_thing(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    name: str,
    action_id: str,
    idempotency_key: str,
    reason: str,
    run_id: UUID | None,
) -> WriteOutcome:
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Thing name must not be empty.")
    previous = await uow.audit.get_mutation(user_id=user_id, idempotency_key=idempotency_key)
    if previous is not None:
        thing = await uow.things.get(user_id=user_id, thing_id=previous.target_id)
        if thing is None:
            raise RuntimeError("Idempotent Thing creation points to a missing Thing.")
        return WriteOutcome(
            code="THING_CREATED",
            message="Thing created.",
            data={"id": str(thing.id), "version": thing.version, "replayed": True},
            mutation_refs=(str(previous.id),),
            mutation_id=previous.id,
            replayed=True,
        )
    await uow.users.ensure_exists(user_id)
    thing = Thing(user_id=user_id, name=normalized_name)
    await uow.things.add(thing)
    await uow.flush()
    mutation = StateMutation(
        user_id=user_id,
        thing_id=thing.id,
        run_id=run_id,
        action_id=action_id,
        mutation_type="THING_CREATED",
        target_type="THING",
        target_id=thing.id,
        after={"name": thing.name, "status": thing.status.value, "version": thing.version},
        reason=reason,
        idempotency_key=idempotency_key,
    )
    await uow.audit.add_mutation(mutation)
    await uow.flush()
    await uow.audit.add_timeline_event(
        TimelineEvent(
            user_id=user_id,
            thing_id=thing.id,
            event_type="THING_CREATED",
            title=f"创建事务：{thing.name}",
            occurred_at=thing.created_at,
            mutation_id=mutation.id,
        )
    )
    return WriteOutcome(
        code="THING_CREATED",
        message="Thing created.",
        data={"id": str(thing.id), "version": thing.version, "replayed": False},
        mutation_refs=(str(mutation.id),),
        mutation_id=mutation.id,
    )


async def apply_transition_task(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    task_id: UUID,
    target_status: TaskStatus,
    expected_version: int,
    action_id: str,
    idempotency_key: str,
    reason: str,
    run_id: UUID | None = None,
) -> WriteOutcome:
    previous = await uow.audit.get_mutation(user_id=user_id, idempotency_key=idempotency_key)
    if previous is not None:
        version = previous.after.get("version")
        if not isinstance(version, int):
            raise RuntimeError("Stored Task mutation is missing target version.")
        return WriteOutcome(
            code="TASK_STATUS_CHANGED",
            message="Task status changed.",
            data={
                "mutation_id": str(previous.id),
                "task_id": str(previous.target_id),
                "version": version,
                "replayed": True,
            },
            mutation_refs=(str(previous.id),),
            mutation_id=previous.id,
            replayed=True,
        )
    task = await uow.tasks.get(user_id=user_id, task_id=task_id)
    if task is None:
        raise EntityNotFound("Task was not found.")
    if task.version != expected_version:
        raise VersionConflict("Task version is stale.")
    before_status = task.status
    task.transition_to(target_status)
    if task.version == expected_version:
        raise ValueError("Task already has the requested status.")
    if not await uow.tasks.update(task, expected_version=expected_version):
        raise VersionConflict("Task was updated concurrently.")
    mutation = StateMutation(
        user_id=user_id,
        thing_id=task.thing_id,
        run_id=run_id,
        action_id=action_id,
        mutation_type="TASK_STATUS_CHANGED",
        target_type="TASK",
        target_id=task.id,
        before={"status": before_status.value, "version": expected_version},
        after={"status": task.status.value, "version": task.version},
        reason=reason,
        idempotency_key=idempotency_key,
    )
    await uow.audit.add_mutation(mutation)
    await uow.flush()
    if task.thing_id is not None:
        await uow.audit.add_timeline_event(
            TimelineEvent(
                user_id=user_id,
                thing_id=task.thing_id,
                event_type="TASK_COMPLETED"
                if task.status is TaskStatus.DONE
                else "TASK_STATUS_CHANGED",
                title=f"任务状态变更：{task.title} → {task.status.value}",
                occurred_at=task.updated_at,
                mutation_id=mutation.id,
            )
        )
    return WriteOutcome(
        code="TASK_STATUS_CHANGED",
        message="Task status changed.",
        data={
            "mutation_id": str(mutation.id),
            "task_id": str(task.id),
            "version": task.version,
            "replayed": False,
        },
        mutation_refs=(str(mutation.id),),
        mutation_id=mutation.id,
    )


async def apply_set_thing_context(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    thing_id: UUID,
    label: str,
    content: str,
    entry_id: UUID | None,
    expected_version: int | None,
    source_id: UUID | None,
    action_id: str,
    idempotency_key: str,
    reason: str,
    run_id: UUID | None,
) -> WriteOutcome:
    normalized_label, normalized_content = label.strip(), content.strip()
    if not normalized_label or not normalized_content:
        raise ValueError("Thing context label and content must not be empty.")
    previous = await uow.audit.get_mutation(user_id=user_id, idempotency_key=idempotency_key)
    if previous is not None:
        version = previous.after.get("version")
        if not isinstance(version, int):
            raise RuntimeError("Stored context mutation is missing target version.")
        return WriteOutcome(
            code="THING_CONTEXT_SET",
            message="Current Thing context set.",
            data={
                "mutation_id": str(previous.id),
                "entry_id": str(previous.target_id),
                "version": version,
                "replayed": True,
            },
            mutation_refs=(str(previous.id),),
            mutation_id=previous.id,
            replayed=True,
        )
    if await uow.things.get(user_id=user_id, thing_id=thing_id) is None:
        raise EntityNotFound("Thing was not found.")
    if entry_id is None:
        if expected_version is not None:
            raise ValueError("expected_version is only valid when updating a context entry.")
        entry = ThingContextEntry(
            thing_id=thing_id,
            label=normalized_label,
            content=normalized_content,
            source_id=source_id,
        )
        await uow.context_entries.add(entry)
        mutation_type = "THING_CONTEXT_CREATED"
        before = None
    else:
        if expected_version is None:
            raise ValueError("expected_version is required when updating a context entry.")
        existing = await uow.context_entries.get(user_id=user_id, entry_id=entry_id)
        if existing is None or existing.thing_id != thing_id:
            raise EntityNotFound("Thing context entry was not found.")
        entry = existing
        if entry.version != expected_version:
            raise VersionConflict("Thing context entry version is stale.")
        before = {"label": entry.label, "content": entry.content, "version": entry.version}
        entry.revise(label=normalized_label, content=normalized_content)
        if not await uow.context_entries.update(entry, expected_version=expected_version):
            raise VersionConflict("Thing context entry was updated concurrently.")
        mutation_type = "THING_CONTEXT_UPDATED"
    await uow.flush()
    mutation = StateMutation(
        user_id=user_id,
        thing_id=thing_id,
        run_id=run_id,
        action_id=action_id,
        mutation_type=mutation_type,
        target_type="THING_CONTEXT_ENTRY",
        target_id=entry.id,
        before=before,
        after={"label": entry.label, "content": entry.content, "version": entry.version},
        reason=reason,
        source_id=source_id,
        idempotency_key=idempotency_key,
    )
    await uow.audit.add_mutation(mutation)
    await uow.flush()
    await uow.audit.add_timeline_event(
        TimelineEvent(
            user_id=user_id,
            thing_id=thing_id,
            event_type=mutation_type,
            title=f"更新当前上下文：{entry.label}",
            occurred_at=entry.updated_at,
            source_id=source_id,
            mutation_id=mutation.id,
        )
    )
    return WriteOutcome(
        code="THING_CONTEXT_SET",
        message="Current Thing context set.",
        data={
            "mutation_id": str(mutation.id),
            "entry_id": str(entry.id),
            "version": entry.version,
            "replayed": False,
        },
        mutation_refs=(str(mutation.id),),
        mutation_id=mutation.id,
    )


def mutation_result_from_outcome(outcome: WriteOutcome) -> MutationResultDTO:
    mutation_id = outcome.mutation_id
    if mutation_id is None:
        raw_mutation_id = outcome.data.get("mutation_id")
        if not isinstance(raw_mutation_id, str):
            raise RuntimeError("Write outcome is missing mutation id.")
        mutation_id = UUID(raw_mutation_id)
    target = outcome.data.get("target_id") or outcome.data.get("thing_id") or outcome.data.get(
        "task_id"
    ) or outcome.data.get("entry_id") or outcome.data.get("date_id") or outcome.data.get(
        "blocker_id"
    ) or outcome.data.get("duplicate_thing_id")
    if not isinstance(target, str):
        raise RuntimeError("Write outcome is missing target id.")
    if outcome.data.get("date_id") == target and isinstance(
        outcome.data.get("date_version"), int
    ):
        version = outcome.data["date_version"]
    else:
        version = outcome.data.get("version")
        if not isinstance(version, int):
            version = outcome.data.get("thing_version")
        if not isinstance(version, int):
            version = outcome.data.get("date_version")
        if not isinstance(version, int):
            version = 1
    return MutationResultDTO(
        mutation_id=mutation_id,
        target_id=UUID(target),
        target_version=version,
        replayed=outcome.replayed,
    )


async def apply_create_task(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    thing_id: UUID | None,
    title: str,
    due_at: datetime | None,
    recurrence_interval_days: int | None,
    action_id: str,
    idempotency_key: str,
    reason: str,
    run_id: UUID | None = None,
) -> WriteOutcome:
    normalized_title = title.strip()
    if not normalized_title:
        raise ValueError("Task title must not be empty.")
    if recurrence_interval_days is not None and (recurrence_interval_days <= 0 or due_at is None):
        raise ValueError("Recurring Task requires a due time and a positive interval.")
    previous = await uow.audit.get_mutation(user_id=user_id, idempotency_key=idempotency_key)
    if previous is not None:
        task = await uow.tasks.get(user_id=user_id, task_id=previous.target_id)
        if task is None:
            raise RuntimeError("Idempotent Task creation points to a missing Task.")
        return WriteOutcome(
            code="TASK_CREATED",
            message="Task created.",
            data={"id": str(task.id), "version": task.version, "replayed": True},
            mutation_refs=(str(previous.id),),
            mutation_id=previous.id,
            replayed=True,
        )
    thing = None
    if thing_id is not None:
        thing = await uow.things.get(user_id=user_id, thing_id=thing_id)
        if thing is None:
            raise EntityNotFound("Thing was not found.")
    await uow.users.ensure_exists(user_id)
    task = Task(
        user_id=user_id,
        thing_id=thing.id if thing else None,
        title=normalized_title,
        due_at=due_at,
        recurrence_interval_days=recurrence_interval_days,
    )
    await uow.tasks.add(task)
    await uow.flush()
    mutation = StateMutation(
        user_id=user_id,
        thing_id=thing.id if thing else None,
        run_id=run_id,
        action_id=action_id,
        mutation_type="TASK_CREATED",
        target_type="TASK",
        target_id=task.id,
        after={
            "title": task.title,
            "status": task.status.value,
            "due_at": task.due_at.isoformat() if task.due_at else None,
            "recurrence_interval_days": task.recurrence_interval_days,
            "version": task.version,
        },
        reason=reason,
        idempotency_key=idempotency_key,
    )
    await uow.audit.add_mutation(mutation)
    await uow.flush()
    if thing is not None:
        await uow.audit.add_timeline_event(
            TimelineEvent(
                user_id=user_id,
                thing_id=thing.id,
                event_type="TASK_CREATED",
                title=f"创建任务：{task.title}",
                occurred_at=task.created_at,
                mutation_id=mutation.id,
            )
        )
    return WriteOutcome(
        code="TASK_CREATED",
        message="Task created.",
        data={"id": str(task.id), "version": task.version, "replayed": False},
        mutation_refs=(str(mutation.id),),
        mutation_id=mutation.id,
    )


async def apply_set_deadline(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    thing_id: UUID,
    kind: ThingDateType,
    value: datetime,
    timezone_name: str,
    precision: DatePrecision,
    certainty: DateCertainty,
    is_primary: bool,
    expected_version: int,
    action_id: str,
    idempotency_key: str,
    reason: str,
    label: str | None = None,
    run_id: UUID | None = None,
    source_id: UUID | None = None,
) -> WriteOutcome:
    if value.tzinfo is None:
        raise ValueError("Deadline must include timezone information.")
    if not timezone_name.strip():
        raise ValueError("Date timezone must not be empty.")
    if is_primary and certainty is not DateCertainty.CONFIRMED:
        raise ValueError("Only a confirmed date can become the primary deadline.")
    previous = await uow.audit.get_mutation(user_id=user_id, idempotency_key=idempotency_key)
    if previous is not None:
        thing_version = previous.after.get("thing_version")
        if not isinstance(thing_version, int):
            raise RuntimeError("Stored deadline mutation is missing Thing version.")
        return WriteOutcome(
            code="DEADLINE_SET",
            message="Deadline set.",
            data={
                "mutation_id": str(previous.id),
                "date_id": str(previous.target_id),
                "thing_version": thing_version,
                "replayed": True,
            },
            mutation_refs=(str(previous.id),),
            mutation_id=previous.id,
            replayed=True,
        )
    thing = await uow.things.get(user_id=user_id, thing_id=thing_id)
    if thing is None:
        raise EntityNotFound("Thing was not found.")
    if thing.version != expected_version:
        raise VersionConflict("Thing version is stale.")
    if (
        source_id is not None
        and await uow.sources.get(user_id=user_id, source_id=source_id) is None
    ):
        raise EntityNotFound("Source was not found.")
    previous_deadline = thing.deadline_at
    thing_date = ThingDate(
        thing_id=thing.id,
        kind=kind,
        label=label.strip() if label else None,
        value=value,
        timezone_name=timezone_name.strip(),
        precision=precision,
        certainty=certainty,
        is_primary=is_primary,
        source_id=source_id,
    )
    if is_primary:
        thing.set_primary_deadline(value)
        if not await uow.things.update(thing, expected_version=expected_version):
            raise VersionConflict("Thing was updated concurrently.")
        await uow.dates.unset_primary(thing_id=thing.id, kind=thing_date.kind)
    await uow.dates.add(thing_date)
    await uow.flush()
    mutation = StateMutation(
        user_id=user_id,
        thing_id=thing.id,
        run_id=run_id,
        action_id=action_id,
        mutation_type="DEADLINE_SET",
        target_type="THING_DATE",
        target_id=thing_date.id,
        before={
            "deadline_at": previous_deadline.isoformat() if previous_deadline is not None else None,
            "thing_version": expected_version,
        },
        after={
            "value": value.isoformat(),
            "certainty": certainty.value,
            "is_primary": is_primary,
            "source_id": str(source_id) if source_id is not None else None,
            "thing_version": thing.version,
            **(
                {"evidence_ref": file_evidence_ref(source_id).to_json()}
                if source_id is not None
                else {}
            ),
        },
        reason=reason,
        idempotency_key=idempotency_key,
    )
    await uow.audit.add_mutation(mutation)
    await uow.flush()
    await uow.audit.add_timeline_event(
        TimelineEvent(
            user_id=user_id,
            thing_id=thing.id,
            event_type="DEADLINE_CHANGED" if is_primary else "IMPORTANT_DATE_ADDED",
            title=f"设置日期：{thing_date.kind}",
            occurred_at=utc_now(),
            mutation_id=mutation.id,
        )
    )
    return WriteOutcome(
        code="DEADLINE_SET",
        message="Deadline set.",
        data={
            "mutation_id": str(mutation.id),
            "date_id": str(thing_date.id),
            "thing_version": thing.version,
            "replayed": False,
        },
        mutation_refs=(str(mutation.id),),
        mutation_id=mutation.id,
    )


async def apply_create_blocker(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    thing_id: UUID,
    description: str,
    severity: BlockerSeverity,
    task_id: UUID | None,
    source_id: UUID | None,
    action_id: str,
    idempotency_key: str,
    reason: str,
) -> WriteOutcome:
    normalized = description.strip()
    if not normalized:
        raise ValueError("Blocker description must not be empty.")
    previous = await uow.audit.get_mutation(user_id=user_id, idempotency_key=idempotency_key)
    if previous is not None:
        blocker = await uow.blockers.get(user_id=user_id, blocker_id=previous.target_id)
        if blocker is None:
            raise RuntimeError("Idempotent Blocker creation points to missing data.")
        return WriteOutcome(
            code="BLOCKER_ADDED",
            message="Blocker added.",
            data={"id": str(blocker.id), "version": blocker.version, "replayed": True},
            mutation_refs=(str(previous.id),),
            mutation_id=previous.id,
            replayed=True,
        )
    if await uow.things.get(user_id=user_id, thing_id=thing_id) is None:
        raise EntityNotFound("Thing was not found.")
    if task_id is not None:
        task = await uow.tasks.get(user_id=user_id, task_id=task_id)
        if task is None or task.thing_id != thing_id:
            raise EntityNotFound("Task was not found in this Thing.")
    if (
        source_id is not None
        and await uow.sources.get(user_id=user_id, source_id=source_id) is None
    ):
        raise EntityNotFound("Source was not found.")
    blocker = Blocker(
        thing_id=thing_id,
        task_id=task_id,
        description=normalized,
        severity=severity,
        source_id=source_id,
    )
    await uow.blockers.add(blocker)
    await uow.flush()
    mutation = StateMutation(
        user_id=user_id,
        thing_id=thing_id,
        action_id=action_id,
        mutation_type="BLOCKER_ADDED",
        target_type="BLOCKER",
        target_id=blocker.id,
        after={"status": blocker.status.value, "version": blocker.version},
        reason=reason,
        source_id=source_id,
        idempotency_key=idempotency_key,
    )
    await uow.audit.add_mutation(mutation)
    await uow.flush()
    await uow.audit.add_timeline_event(
        TimelineEvent(
            user_id=user_id,
            thing_id=thing_id,
            event_type="BLOCKER_ADDED",
            title=f"新增阻碍：{blocker.description}",
            occurred_at=blocker.blocked_since,
            source_id=source_id,
            mutation_id=mutation.id,
        )
    )
    return WriteOutcome(
        code="BLOCKER_ADDED",
        message="Blocker added.",
        data={"id": str(blocker.id), "version": blocker.version, "replayed": False},
        mutation_refs=(str(mutation.id),),
        mutation_id=mutation.id,
    )


async def apply_resolve_blocker(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    blocker_id: UUID,
    expected_version: int,
    action_id: str,
    idempotency_key: str,
    reason: str,
) -> WriteOutcome:
    previous = await uow.audit.get_mutation(user_id=user_id, idempotency_key=idempotency_key)
    if previous is not None:
        version = previous.after.get("version")
        if not isinstance(version, int):
            raise RuntimeError("Stored Blocker mutation is missing target version.")
        return WriteOutcome(
            code="BLOCKER_RESOLVED",
            message="Blocker resolved.",
            data={
                "mutation_id": str(previous.id),
                "blocker_id": str(previous.target_id),
                "version": version,
                "replayed": True,
            },
            mutation_refs=(str(previous.id),),
            mutation_id=previous.id,
            replayed=True,
        )
    blocker = await uow.blockers.get(user_id=user_id, blocker_id=blocker_id)
    if blocker is None:
        raise EntityNotFound("Blocker was not found.")
    if blocker.version != expected_version:
        raise VersionConflict("Blocker version is stale.")
    blocker.resolve()
    if not await uow.blockers.update(blocker, expected_version=expected_version):
        raise VersionConflict("Blocker was updated concurrently.")
    mutation = StateMutation(
        user_id=user_id,
        thing_id=blocker.thing_id,
        action_id=action_id,
        mutation_type="BLOCKER_RESOLVED",
        target_type="BLOCKER",
        target_id=blocker.id,
        before={"status": "OPEN", "version": expected_version},
        after={"status": blocker.status.value, "version": blocker.version},
        reason=reason,
        idempotency_key=idempotency_key,
    )
    await uow.audit.add_mutation(mutation)
    await uow.flush()
    await uow.audit.add_timeline_event(
        TimelineEvent(
            user_id=user_id,
            thing_id=blocker.thing_id,
            event_type="BLOCKER_RESOLVED",
            title=f"解决阻碍：{blocker.description}",
            occurred_at=blocker.resolved_at or utc_now(),
            mutation_id=mutation.id,
        )
    )
    return WriteOutcome(
        code="BLOCKER_RESOLVED",
        message="Blocker resolved.",
        data={
            "mutation_id": str(mutation.id),
            "blocker_id": str(blocker.id),
            "version": blocker.version,
            "replayed": False,
        },
        mutation_refs=(str(mutation.id),),
        mutation_id=mutation.id,
    )


async def apply_merge_things(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    canonical_thing_id: UUID,
    duplicate_thing_id: UUID,
    expected_canonical_version: int,
    expected_duplicate_version: int,
    action_id: str,
    idempotency_key: str,
    reason: str,
    run_id: UUID | None = None,
) -> WriteOutcome:
    if canonical_thing_id == duplicate_thing_id:
        raise ValueError("Canonical and duplicate Thing IDs must differ.")
    previous = await uow.audit.get_mutation(user_id=user_id, idempotency_key=idempotency_key)
    if previous is not None:
        version = previous.after.get("version")
        if not isinstance(version, int):
            raise RuntimeError("Stored merge mutation is missing target version.")
        return WriteOutcome(
            code="THING_MERGED",
            message="Things merged.",
            data={
                "mutation_id": str(previous.id),
                "duplicate_thing_id": str(previous.target_id),
                "canonical_thing_id": str(previous.after.get("canonical_thing_id", "")),
                "version": version,
                "replayed": True,
            },
            mutation_refs=(str(previous.id),),
            mutation_id=previous.id,
            replayed=True,
        )
    canonical = await uow.things.get(user_id=user_id, thing_id=canonical_thing_id)
    duplicate = await uow.things.get(user_id=user_id, thing_id=duplicate_thing_id)
    if canonical is None or duplicate is None:
        raise EntityNotFound("Canonical or duplicate Thing was not found.")
    if canonical.version != expected_canonical_version:
        raise VersionConflict("Canonical Thing version is stale.")
    if duplicate.version != expected_duplicate_version:
        raise VersionConflict("Duplicate Thing version is stale.")
    duplicate.merge_into(canonical_thing_id=canonical.id)
    if not await uow.things.update(duplicate, expected_version=expected_duplicate_version):
        raise VersionConflict("Duplicate Thing was updated concurrently.")
    await uow.things.rebind_merged_references(
        duplicate_thing_id=duplicate.id, canonical_thing_id=canonical.id
    )
    mutation = StateMutation(
        user_id=user_id,
        thing_id=duplicate.id,
        run_id=run_id,
        action_id=action_id,
        mutation_type="THING_MERGED",
        target_type="THING",
        target_id=duplicate.id,
        before={"merged_into_thing_id": None, "version": expected_duplicate_version},
        after={
            "merged_into_thing_id": str(canonical.id),
            "canonical_thing_id": str(canonical.id),
            "version": duplicate.version,
        },
        reason=reason,
        idempotency_key=idempotency_key,
    )
    await uow.audit.add_mutation(mutation)
    await uow.flush()
    await uow.audit.add_timeline_event(
        TimelineEvent(
            user_id=user_id,
            thing_id=canonical.id,
            event_type="THING_MERGED",
            title=f"Merged duplicate Thing: {duplicate.name}",
            occurred_at=duplicate.updated_at,
            mutation_id=mutation.id,
            metadata={"duplicate_thing_id": str(duplicate.id)},
        )
    )
    return WriteOutcome(
        code="THING_MERGED",
        message="Things merged.",
        data={
            "mutation_id": str(mutation.id),
            "duplicate_thing_id": str(duplicate.id),
            "canonical_thing_id": str(canonical.id),
            "version": duplicate.version,
            "replayed": False,
        },
        mutation_refs=(str(mutation.id),),
        mutation_id=mutation.id,
    )


async def apply_complete_task(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    task_id: UUID,
    expected_version: int,
    action_id: str,
    idempotency_key: str,
    reason: str,
    run_id: UUID | None = None,
) -> WriteOutcome:
    previous = await uow.audit.get_mutation(user_id=user_id, idempotency_key=idempotency_key)
    if previous is not None:
        version = previous.after.get("version")
        if not isinstance(version, int):
            raise RuntimeError("Stored mutation is missing a valid target version.")
        return WriteOutcome(
            code="TASK_COMPLETED",
            message="Task completed.",
            data={
                "mutation_id": str(previous.id),
                "task_id": str(previous.target_id),
                "version": version,
                "replayed": True,
            },
            mutation_refs=(str(previous.id),),
            mutation_id=previous.id,
            replayed=True,
        )
    task = await uow.tasks.get(user_id=user_id, task_id=task_id)
    if task is None:
        raise EntityNotFound("Task was not found.")
    if task.version != expected_version:
        raise VersionConflict("Task version is stale.")
    before: dict[str, object] = {"status": task.status.value, "version": task.version}
    task.complete()
    if not await uow.tasks.update(task, expected_version=expected_version):
        raise VersionConflict("Task was updated concurrently.")
    mutation_type = (
        "RECURRING_TASK_ADVANCED"
        if task.recurrence_interval_days is not None
        else "TASK_COMPLETED"
    )
    mutation = StateMutation(
        user_id=user_id,
        thing_id=task.thing_id,
        run_id=run_id,
        action_id=action_id,
        mutation_type=mutation_type,
        target_type="TASK",
        target_id=task.id,
        before=before,
        after={
            "status": task.status.value,
            "due_at": task.due_at.isoformat() if task.due_at else None,
            "version": task.version,
        },
        reason=reason,
        idempotency_key=idempotency_key,
    )
    await uow.audit.add_mutation(mutation)
    await uow.flush()
    if task.thing_id is not None:
        await uow.audit.add_timeline_event(
            TimelineEvent(
                user_id=user_id,
                thing_id=task.thing_id,
                event_type="TASK_COMPLETED",
                title=f"{task.title}已完成",
                occurred_at=task.completed_at or utc_now(),
                mutation_id=mutation.id,
            )
        )
    return WriteOutcome(
        code="TASK_COMPLETED",
        message="Task completed.",
        data={
            "mutation_id": str(mutation.id),
            "task_id": str(task.id),
            "version": task.version,
            "replayed": False,
        },
        mutation_refs=(str(mutation.id),),
        mutation_id=mutation.id,
    )


async def apply_update_date(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    date_id: UUID,
    value: datetime,
    timezone_name: str,
    precision: DatePrecision,
    certainty: DateCertainty,
    is_primary: bool,
    expected_version: int,
    expected_thing_version: int,
    action_id: str,
    idempotency_key: str,
    reason: str,
) -> WriteOutcome:
    previous = await uow.audit.get_mutation(user_id=user_id, idempotency_key=idempotency_key)
    if previous is not None:
        date_version = previous.after.get("date_version")
        if not isinstance(date_version, int):
            raise RuntimeError("Stored date mutation is missing target version.")
        return WriteOutcome(
            code="DATE_UPDATED",
            message="Date updated.",
            data={
                "mutation_id": str(previous.id),
                "date_id": str(previous.target_id),
                "date_version": date_version,
                "replayed": True,
            },
            mutation_refs=(str(previous.id),),
            mutation_id=previous.id,
            replayed=True,
        )
    thing_date = await uow.dates.get(user_id=user_id, date_id=date_id)
    if thing_date is None:
        raise EntityNotFound("ThingDate was not found.")
    if thing_date.version != expected_version:
        raise VersionConflict("ThingDate version is stale.")
    thing = await uow.things.get(user_id=user_id, thing_id=thing_date.thing_id)
    if thing is None:
        raise EntityNotFound("Thing was not found.")
    if thing.version != expected_thing_version:
        raise VersionConflict("Thing version is stale.")
    before: dict[str, object] = {
        "value": thing_date.value.isoformat(),
        "certainty": thing_date.certainty.value,
        "is_primary": thing_date.is_primary,
        "date_version": thing_date.version,
        "thing_version": thing.version,
    }
    was_primary = thing_date.is_primary
    thing_date.revise(
        value=value,
        timezone_name=timezone_name,
        precision=precision,
        certainty=certainty,
        is_primary=is_primary,
    )
    if is_primary:
        await uow.dates.unset_primary(thing_id=thing.id, kind=thing_date.kind)
        thing.set_primary_deadline(value)
    elif was_primary:
        thing.deadline_at = None
        thing.touch()
    if thing.version != expected_thing_version and not await uow.things.update(
        thing, expected_version=expected_thing_version
    ):
        raise VersionConflict("Thing was updated concurrently.")
    if not await uow.dates.update(thing_date, expected_version=expected_version):
        raise VersionConflict("ThingDate was updated concurrently.")
    mutation = StateMutation(
        user_id=user_id,
        thing_id=thing.id,
        action_id=action_id,
        mutation_type="DATE_UPDATED",
        target_type="THING_DATE",
        target_id=thing_date.id,
        before=before,
        after={
            "value": thing_date.value.isoformat(),
            "certainty": thing_date.certainty.value,
            "is_primary": thing_date.is_primary,
            "date_version": thing_date.version,
            "thing_version": thing.version,
        },
        reason=reason,
        idempotency_key=idempotency_key,
    )
    await uow.audit.add_mutation(mutation)
    await uow.flush()
    await uow.audit.add_timeline_event(
        TimelineEvent(
            user_id=user_id,
            thing_id=thing.id,
            event_type="DEADLINE_CHANGED" if is_primary or was_primary else "DATE_CHANGED",
            title=f"更新日期：{thing_date.kind}",
            occurred_at=thing_date.updated_at,
            mutation_id=mutation.id,
        )
    )
    return WriteOutcome(
        code="DATE_UPDATED",
        message="Date updated.",
        data={
            "mutation_id": str(mutation.id),
            "date_id": str(thing_date.id),
            "date_version": thing_date.version,
            "thing_version": thing.version,
            "replayed": False,
        },
        mutation_refs=(str(mutation.id),),
        mutation_id=mutation.id,
    )
