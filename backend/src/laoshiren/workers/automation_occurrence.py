"""Worker that settles AUTOMATION_OCCURRENCE durable jobs."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from laoshiren.application.automations.materialize import scheduled_slot_key
from laoshiren.application.automations.notification_pipeline import create_reminder_notification
from laoshiren.application.automations.ports import AutomationRunTrigger, AutomationUnitOfWork
from laoshiren.application.runtime.durable_job_claim import claim_ready_jobs
from laoshiren.domain.automations.value_objects import OccurrenceStatus
from laoshiren.domain.runtime.entities import DurableJobKind, DurableJobStatus

logger = logging.getLogger(__name__)

UnitOfWorkFactory = Callable[[], AutomationUnitOfWork]


class AutomationOccurrenceWorker:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        run_trigger: AutomationRunTrigger | None = None,
        *,
        worker_id: str | None = None,
        lease_seconds: float = 120.0,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("Automation occurrence lease must be positive.")
        self._unit_of_work_factory = unit_of_work_factory
        self._run_trigger = run_trigger
        self._worker_id = worker_id or f"automation-occurrence-{uuid4()}"
        self._lease_seconds = lease_seconds

    async def run_once(self) -> bool:
        now = datetime.now(UTC)
        async with self._unit_of_work_factory() as unit_of_work:
            jobs = await claim_ready_jobs(
                unit_of_work,
                kind=DurableJobKind.AUTOMATION_OCCURRENCE,
                owner=self._worker_id,
                now=now,
                lease_until=now + timedelta(seconds=self._lease_seconds),
                limit=1,
            )
            if not jobs:
                await unit_of_work.rollback()
                return False
            job = jobs[0]
            await unit_of_work.commit()

        occurrence_id = UUID(str(job.payload["occurrence_id"]))
        automation_id = UUID(str(job.payload["automation_id"]))
        try:
            async with self._unit_of_work_factory() as unit_of_work:
                occurrence = await unit_of_work.occurrences.get(occurrence_id=occurrence_id)
                if occurrence is None or occurrence.status is not OccurrenceStatus.MATERIALIZED:
                    await unit_of_work.rollback()
                else:
                    automation = await unit_of_work.automations.get(
                        user_id=job.user_id, automation_id=automation_id
                    )
                    if automation is None:
                        occurrence.fail()
                        await unit_of_work.occurrences.update(occurrence)
                    elif occurrence.definition_revision != automation.definition_revision:
                        occurrence.skip()
                        await unit_of_work.occurrences.update(occurrence)
                    else:
                        occurrence_key = scheduled_slot_key(
                            automation_id=automation.id,
                            definition_revision=occurrence.definition_revision,
                            scheduled_for=occurrence.scheduled_for,
                        )
                        if self._run_trigger is not None:
                            await self._run_trigger.trigger_from_occurrence(
                                user_id=automation.user_id,
                                automation_id=automation.id,
                                thing_id=automation.thing_id,
                                title=automation.title,
                                message=automation.message,
                                occurrence_key=occurrence_key,
                            )
                        await create_reminder_notification(
                            unit_of_work,
                            automation=automation,
                            occurrence=occurrence,
                        )
                        occurrence.succeed()
                        await unit_of_work.occurrences.update(occurrence)
                    await unit_of_work.commit()
        except Exception:
            logger.exception(
                "automation_occurrence_failed",
                extra={"occurrence_id": str(occurrence_id), "job_id": str(job.id)},
            )

        async with self._unit_of_work_factory() as unit_of_work:
            settled = await unit_of_work.durable_jobs.settle(
                job_id=job.id,
                owner=self._worker_id,
                claim_epoch=job.claim_epoch,
                status=DurableJobStatus.COMPLETED,
                now=datetime.now(UTC),
            )
            if settled:
                await unit_of_work.commit()
            else:
                await unit_of_work.rollback()
        return True
