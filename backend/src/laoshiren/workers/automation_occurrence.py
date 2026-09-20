"""Worker that settles AUTOMATION_OCCURRENCE durable jobs."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from laoshiren.application.automations.occurrence_execution import (
    AutomationOccurrenceApplicationService,
    OccurrenceExecutionResult,
)
from laoshiren.application.automations.ports import AutomationUnitOfWork
from laoshiren.application.runtime.durable_job_claim import claim_ready_jobs
from laoshiren.domain.runtime.entities import DurableJobKind

logger = logging.getLogger(__name__)

UnitOfWorkFactory = Callable[[], AutomationUnitOfWork]


class AutomationOccurrenceWorker:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        execution_service: AutomationOccurrenceApplicationService,
        *,
        worker_id: str | None = None,
        lease_seconds: float = 120.0,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("Automation occurrence lease must be positive.")
        self._unit_of_work_factory = unit_of_work_factory
        self._execution_service = execution_service
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
                await unit_of_work.commit()
                await self._execution_service.reconcile_exhausted()
                return False
            job = jobs[0]
            await unit_of_work.commit()

        await self._execution_service.reconcile_exhausted()

        try:
            result = await self._execution_service.execute_claimed(
                job=job, owner=self._worker_id
            )
        except Exception:
            logger.exception(
                "automation_occurrence_failed",
                extra={"job_id": str(job.id)},
            )
            try:
                result = await self._execution_service.record_failure(
                    job=job, owner=self._worker_id
                )
            except Exception:
                # Keep the claim for lease recovery if PostgreSQL is unavailable.
                logger.exception(
                    "automation_occurrence_recovery_failed", extra={"job_id": str(job.id)}
                )
                return True
        if result is OccurrenceExecutionResult.FAILED:
            logger.error("automation_occurrence_terminal_failure", extra={"job_id": str(job.id)})
        return True
