"""Automation mutations that run inside a shared Unit of Work (no commit)."""

from datetime import datetime
from uuid import UUID

from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.application.personal_state.write_ops import WriteOutcome
from laoshiren.domain.automations.entities import Automation, AutomationStatus, AutomationType
from laoshiren.domain.personal_state.exceptions import EntityNotFound, VersionConflict


async def apply_create_automation(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    automation_type: AutomationType,
    title: str,
    message: str,
    timezone_name: str,
    next_trigger_at: datetime,
    idempotency_key: str,
    thing_id: UUID | None = None,
    task_id: UUID | None = None,
    source_id: UUID | None = None,
    recurrence_interval_seconds: int | None = None,
) -> WriteOutcome:
    if not title.strip() or not message.strip() or not timezone_name.strip():
        raise ValueError("Automation title, message and timezone must not be empty.")
    previous = await uow.automations.get_by_idempotency(user_id=user_id, key=idempotency_key)
    if previous is not None:
        return WriteOutcome(
            code="AUTOMATION_CREATED",
            message="Automation created.",
            data={
                "id": str(previous.id),
                "status": previous.status.value,
                "version": previous.version,
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
    if task_id is not None:
        task = await uow.tasks.get(user_id=user_id, task_id=task_id)
        if task is None or (thing_id is not None and task.thing_id != thing_id):
            raise EntityNotFound("Task was not found in the selected Thing.")
    if (
        source_id is not None
        and await uow.sources.get(user_id=user_id, source_id=source_id) is None
    ):
        raise EntityNotFound("Source was not found.")
    automation = Automation(
        user_id=user_id,
        automation_type=automation_type,
        title=title.strip(),
        message=message.strip(),
        timezone_name=timezone_name.strip(),
        next_trigger_at=next_trigger_at,
        idempotency_key=idempotency_key,
        thing_id=thing_id,
        task_id=task_id,
        source_id=source_id,
        recurrence_interval_seconds=recurrence_interval_seconds,
        status=AutomationStatus.PAUSED
        if automation_type in {AutomationType.CONDITION_WATCH, AutomationType.CONDITION}
        else AutomationStatus.ACTIVE,
    )
    await uow.automations.add(automation)
    await uow.flush()
    return WriteOutcome(
        code="AUTOMATION_CREATED",
        message="Automation created.",
        data={
            "id": str(automation.id),
            "status": automation.status.value,
            "version": automation.version,
            "replayed": False,
        },
        mutation_refs=(),
    )


async def apply_change_automation_status(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    automation_id: UUID,
    action: str,
    expected_version: int,
    idempotency_key: str,
) -> WriteOutcome:
    operation = await uow.automations.get_operation(user_id=user_id, key=idempotency_key)
    if operation is not None:
        recorded_id, _ = operation
        automation = await uow.automations.get(user_id=user_id, automation_id=recorded_id)
        if automation is None:
            raise RuntimeError("Automation operation points to missing data.")
        code = "AUTOMATION_CANCELLED" if action == "CANCEL" else "AUTOMATION_CHANGED"
        return WriteOutcome(
            code=code,
            message="Automation status changed.",
            data={
                "id": str(automation.id),
                "status": automation.status.value,
                "version": automation.version,
                "replayed": True,
            },
            mutation_refs=(),
            replayed=True,
        )
    automation = await uow.automations.get(user_id=user_id, automation_id=automation_id)
    if automation is None:
        raise EntityNotFound("Automation was not found.")
    if automation.version != expected_version:
        raise VersionConflict("Automation version is stale.")
    if action == "PAUSE":
        automation.pause()
    elif action == "RESUME":
        if automation.automation_type in {
            AutomationType.CONDITION_WATCH,
            AutomationType.CONDITION,
        }:
            raise ValueError("Condition watch execution requires the Agent phase.")
        automation.resume()
    elif action == "CANCEL":
        automation.cancel()
    else:
        raise ValueError("Unsupported Automation action.")
    if not await uow.automations.update(automation, expected_version=expected_version):
        raise VersionConflict("Automation was updated concurrently.")
    await uow.automations.record_operation(
        user_id=user_id,
        automation_id=automation.id,
        key=idempotency_key,
        target_version=automation.version,
    )
    code = "AUTOMATION_CANCELLED" if action == "CANCEL" else "AUTOMATION_CHANGED"
    return WriteOutcome(
        code=code,
        message="Automation status changed.",
        data={
            "id": str(automation.id),
            "status": automation.status.value,
            "version": automation.version,
            "replayed": False,
        },
        mutation_refs=(),
    )
