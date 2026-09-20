"""Settle one claimed Automation occurrence and its durable reaction atomically."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from laoshiren.application.automations.materialize import scheduled_slot_key
from laoshiren.application.automations.notification_pipeline import create_reminder_notification
from laoshiren.application.automations.ports import AutomationRunTrigger, AutomationUnitOfWork
from laoshiren.domain.automations.entities import Automation, AutomationStatus
from laoshiren.domain.automations.value_objects import OccurrenceStatus
from laoshiren.domain.personal_state.exceptions import VersionConflict
from laoshiren.domain.runtime.entities import DurableJob, DurableJobStatus

UnitOfWorkFactory = Callable[[], AutomationUnitOfWork]


class OccurrenceExecutionResult(StrEnum):
    COMPLETED = "COMPLETED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    FAILED = "FAILED"
    LOST_CLAIM = "LOST_CLAIM"


class AutomationOccurrenceApplicationService:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        run_trigger: AutomationRunTrigger | None = None,
        *,
        retry_base_seconds: float = 30.0,
        retry_max_seconds: float = 900.0,
    ) -> None:
        if retry_base_seconds <= 0 or retry_max_seconds < retry_base_seconds:
            raise ValueError("Occurrence retry bounds must be positive and ordered.")
        self._unit_of_work_factory = unit_of_work_factory
        self._run_trigger = run_trigger
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds

    async def execute_claimed(
        self, *, job: DurableJob, owner: str
    ) -> OccurrenceExecutionResult:
        occurrence_id = UUID(str(job.payload["occurrence_id"]))
        automation_id = UUID(str(job.payload["automation_id"]))
        async with self._unit_of_work_factory() as uow:
            claimed = await uow.durable_jobs.get_by_dedupe_key(
                user_id=job.user_id, dedupe_key=job.dedupe_key
            )
            if not self._owns_claim(claimed, job=job, owner=owner):
                await uow.rollback()
                return OccurrenceExecutionResult.LOST_CLAIM

            occurrence = await uow.occurrences.get(occurrence_id=occurrence_id)
            error_code: str | None = None
            if occurrence is None or occurrence.automation_id != automation_id:
                status = DurableJobStatus.FAILED
                error_code = "OCCURRENCE_NOT_FOUND"
            elif occurrence.status is OccurrenceStatus.SUCCEEDED:
                key = scheduled_slot_key(
                    automation_id=automation_id,
                    definition_revision=occurrence.definition_revision,
                    scheduled_for=occurrence.scheduled_for,
                )
                intent = await uow.notification_intents.get_by_dedupe_key(dedupe_key=key)
                status = (
                    DurableJobStatus.COMPLETED
                    if intent is not None
                    else DurableJobStatus.FAILED
                )
                error_code = None if intent is not None else "OCCURRENCE_INTENT_MISSING"
            elif occurrence.status in {OccurrenceStatus.CANCELLED, OccurrenceStatus.SKIPPED}:
                status = DurableJobStatus.COMPLETED
                error_code = None
            elif occurrence.status is OccurrenceStatus.FAILED:
                status = DurableJobStatus.FAILED
                error_code = "OCCURRENCE_ALREADY_FAILED"
            else:
                automation = await uow.automations.get(
                    user_id=job.user_id, automation_id=automation_id
                )
                if automation is None:
                    occurrence.fail()
                    await uow.occurrences.update(occurrence)
                    status = DurableJobStatus.FAILED
                    error_code = "AUTOMATION_NOT_FOUND"
                elif (
                    occurrence.definition_revision != automation.definition_revision
                    or automation.status is AutomationStatus.CANCELLED
                ):
                    occurrence.skip()
                    await uow.occurrences.update(occurrence)
                    status = DurableJobStatus.COMPLETED
                    error_code = None
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
                        uow, automation=automation, occurrence=occurrence
                    )
                    occurrence.succeed()
                    await uow.occurrences.update(occurrence)
                    await self._complete_one_shot(uow, automation)
                    status = DurableJobStatus.COMPLETED
                    error_code = None

            settled = await uow.durable_jobs.settle(
                job_id=job.id,
                owner=owner,
                claim_epoch=job.claim_epoch,
                status=status,
                now=datetime.now(UTC),
                error_code=error_code,
            )
            if not settled:
                await uow.rollback()
                return OccurrenceExecutionResult.LOST_CLAIM
            await uow.commit()
            return (
                OccurrenceExecutionResult.COMPLETED
                if status is DurableJobStatus.COMPLETED
                else OccurrenceExecutionResult.FAILED
            )

    async def record_failure(
        self, *, job: DurableJob, owner: str
    ) -> OccurrenceExecutionResult:
        now = datetime.now(UTC)
        async with self._unit_of_work_factory() as uow:
            claimed = await uow.durable_jobs.get_by_dedupe_key(
                user_id=job.user_id, dedupe_key=job.dedupe_key
            )
            if not self._owns_claim(claimed, job=job, owner=owner):
                await uow.rollback()
                return OccurrenceExecutionResult.LOST_CLAIM
            if job.delivery_attempt < job.max_delivery_attempts:
                backoff = min(
                    self._retry_base_seconds * 2 ** (job.delivery_attempt - 1),
                    self._retry_max_seconds,
                )
                released = await uow.durable_jobs.release_for_retry(
                    job_id=job.id,
                    owner=owner,
                    claim_epoch=job.claim_epoch,
                    available_at=now + timedelta(seconds=backoff),
                    now=now,
                    error_code="OCCURRENCE_EXECUTION_RETRY",
                )
                result = OccurrenceExecutionResult.RETRY_SCHEDULED
            else:
                occurrence_id = UUID(str(job.payload["occurrence_id"]))
                occurrence = await uow.occurrences.get(occurrence_id=occurrence_id)
                if occurrence is not None and occurrence.status is OccurrenceStatus.MATERIALIZED:
                    occurrence.fail()
                    await uow.occurrences.update(occurrence)
                    automation = await uow.automations.get(
                        user_id=job.user_id, automation_id=occurrence.automation_id
                    )
                    if (
                        automation is not None
                        and automation.definition_revision == occurrence.definition_revision
                    ):
                        await self._complete_one_shot(uow, automation)
                released = await uow.durable_jobs.settle(
                    job_id=job.id,
                    owner=owner,
                    claim_epoch=job.claim_epoch,
                    status=DurableJobStatus.FAILED,
                    now=now,
                    error_code="OCCURRENCE_RETRY_EXHAUSTED",
                )
                result = OccurrenceExecutionResult.FAILED
            if not released:
                await uow.rollback()
                return OccurrenceExecutionResult.LOST_CLAIM
            await uow.commit()
            return result

    async def reconcile_exhausted(self) -> int:
        """Reflect lease-recovery exhaustion in the logical Occurrence outcome."""
        async with self._unit_of_work_factory() as uow:
            settled = await uow.occurrences.fail_exhausted(now=datetime.now(UTC))
            for user_id, automation_id, definition_revision in set(settled):
                automation = await uow.automations.get(
                    user_id=user_id, automation_id=automation_id
                )
                if automation is not None and automation.definition_revision == definition_revision:
                    await self._complete_one_shot(uow, automation)
            await uow.commit()
            return len(settled)

    @staticmethod
    async def _complete_one_shot(uow: AutomationUnitOfWork, automation: Automation) -> None:
        expected_version = automation.version
        automation.complete_one_shot()
        if automation.version != expected_version and not await uow.automations.update(
            automation, expected_version=expected_version
        ):
            raise VersionConflict("Automation changed while settling an occurrence.")

    @staticmethod
    def _owns_claim(claimed: DurableJob | None, *, job: DurableJob, owner: str) -> bool:
        return bool(
            claimed is not None
            and claimed.id == job.id
            and claimed.status is DurableJobStatus.CLAIMED
            and claimed.claimed_by == owner
            and claimed.claim_epoch == job.claim_epoch
            and claimed.lease_until is not None
            and claimed.lease_until >= datetime.now(UTC)
        )
