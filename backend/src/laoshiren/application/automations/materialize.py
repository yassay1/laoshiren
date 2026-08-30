"""Atomic Occurrence materialization for due Automations."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from laoshiren.application.automations.ports import AutomationUnitOfWork
from laoshiren.domain.automations.entities import Automation, AutomationOccurrence
from laoshiren.domain.automations.value_objects import MisfirePolicy, OccurrenceStatus
from laoshiren.domain.personal_state.exceptions import VersionConflict
from laoshiren.domain.personal_state.value_objects import TaskStatus
from laoshiren.domain.runtime.entities import DurableJob, DurableJobKind

MISFIRE_HORIZON = timedelta(hours=24)


def occurrence_dedupe_key(occurrence_id: UUID) -> str:
    return f"AUTOMATION_OCCURRENCE:{occurrence_id}"


def scheduled_slot_key(
    *,
    automation_id: UUID,
    definition_revision: int,
    scheduled_for: datetime,
) -> str:
    return (
        f"{automation_id}:{definition_revision}:"
        f"{scheduled_for.astimezone(UTC).isoformat()}"
    )


async def materialize_due_automation(
    uow: AutomationUnitOfWork,
    *,
    automation: Automation,
    occurred_at: datetime,
) -> AutomationOccurrence | None:
    expected_version = automation.version
    if automation.task_id is not None:
        task = await uow.tasks.get(user_id=automation.user_id, task_id=automation.task_id)
        if task is None or task.status in {TaskStatus.DONE, TaskStatus.CANCELLED}:
            automation.cancel()
            if not await uow.automations.update(automation, expected_version=expected_version):
                raise VersionConflict("Automation was claimed concurrently.")
            return None

    scheduled_for = automation.next_trigger_at
    if (
        automation.misfire_policy is MisfirePolicy.SKIP
        and occurred_at - scheduled_for > MISFIRE_HORIZON
    ):
        occurrence = AutomationOccurrence(
            user_id=automation.user_id,
            automation_id=automation.id,
            definition_revision=automation.definition_revision,
            scheduled_for=scheduled_for,
            status=OccurrenceStatus.SKIPPED,
            settled_at=occurred_at,
        )
        created = await uow.occurrences.add(occurrence)
        if not created:
            return None
        automation.mark_triggered(occurred_at)
        if not await uow.automations.update(automation, expected_version=expected_version):
            raise VersionConflict("Automation was claimed concurrently.")
        return occurrence

    occurrence = AutomationOccurrence(
        user_id=automation.user_id,
        automation_id=automation.id,
        definition_revision=automation.definition_revision,
        scheduled_for=scheduled_for,
    )
    created = await uow.occurrences.add(occurrence)
    if not created:
        return None

    job = DurableJob(
        user_id=automation.user_id,
        kind=DurableJobKind.AUTOMATION_OCCURRENCE,
        dedupe_key=occurrence_dedupe_key(occurrence.id),
        payload={
            "occurrence_id": str(occurrence.id),
            "automation_id": str(automation.id),
            "scheduled_for": scheduled_for.astimezone(UTC).isoformat(),
        },
        available_at=occurred_at,
    )
    await uow.durable_jobs.add(job)
    occurrence.durable_job_id = job.id
    await uow.occurrences.update(occurrence)

    automation.mark_triggered(occurred_at)
    if not await uow.automations.update(automation, expected_version=expected_version):
        raise VersionConflict("Automation was claimed concurrently.")
    return occurrence
