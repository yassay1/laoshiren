from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from laoshiren.application.automations.occurrence_execution import (
    AutomationOccurrenceApplicationService,
    OccurrenceExecutionResult,
)
from laoshiren.domain.automations.entities import (
    Automation,
    AutomationOccurrence,
    AutomationStatus,
    AutomationType,
)
from laoshiren.domain.automations.value_objects import OccurrenceStatus
from laoshiren.domain.runtime.entities import DurableJob, DurableJobKind, DurableJobStatus

pytestmark = pytest.mark.asyncio


class FakeUow:
    def __init__(self, job: DurableJob, occurrence: AutomationOccurrence, automation: Automation):
        self.durable_jobs = SimpleNamespace(
            get_by_dedupe_key=AsyncMock(return_value=job),
            settle=AsyncMock(return_value=True),
            release_for_retry=AsyncMock(return_value=True),
        )
        self.occurrences = SimpleNamespace(
            get=AsyncMock(return_value=occurrence),
            update=AsyncMock(),
        )
        self.automations = SimpleNamespace(
            get=AsyncMock(return_value=automation), update=AsyncMock(return_value=True)
        )
        self.notification_intents = SimpleNamespace(
            get_by_dedupe_key=AsyncMock(return_value=None),
            add=AsyncMock(return_value=True),
        )
        self.notification_deliveries = SimpleNamespace(add=AsyncMock(return_value=True))
        self.push_endpoints = SimpleNamespace(list_eligible=AsyncMock(return_value=[]))
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, *_):
        if exc_type is not None:
            await self.rollback()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def claimed_occurrence(*, attempt: int = 1):
    now = datetime.now(UTC)
    user_id = uuid4()
    automation = Automation(
        user_id=user_id,
        automation_type=AutomationType.ONCE,
        title="Submit",
        message="Check submission",
        timezone_name="Asia/Shanghai",
        next_trigger_at=now,
        idempotency_key=str(uuid4()),
    )
    occurrence = AutomationOccurrence(
        user_id=user_id,
        automation_id=automation.id,
        definition_revision=automation.definition_revision,
        scheduled_for=now,
    )
    job = DurableJob(
        user_id=user_id,
        kind=DurableJobKind.AUTOMATION_OCCURRENCE,
        dedupe_key=f"AUTOMATION_OCCURRENCE:{occurrence.id}",
        payload={"occurrence_id": str(occurrence.id), "automation_id": str(automation.id)},
        available_at=now,
    )
    job.claim(owner="worker", lease_until=now + timedelta(minutes=2))
    job.delivery_attempt = attempt
    return job, occurrence, automation


async def test_success_commits_intent_occurrence_and_job_together() -> None:
    job, occurrence, automation = claimed_occurrence()
    uow = FakeUow(job, occurrence, automation)
    service = AutomationOccurrenceApplicationService(lambda: uow)

    result = await service.execute_claimed(job=job, owner="worker")

    assert result is OccurrenceExecutionResult.COMPLETED
    assert occurrence.status is OccurrenceStatus.SUCCEEDED
    assert automation.status is AutomationStatus.COMPLETED
    uow.automations.update.assert_awaited_once()
    uow.notification_intents.add.assert_awaited_once()
    uow.durable_jobs.settle.assert_awaited_once()
    assert uow.durable_jobs.settle.call_args.kwargs["status"] is DurableJobStatus.COMPLETED
    assert uow.commits == 1


async def test_notification_error_schedules_retry_without_completing_job() -> None:
    job, occurrence, automation = claimed_occurrence()
    uow = FakeUow(job, occurrence, automation)
    uow.notification_intents.add.side_effect = RuntimeError("database write failed")
    service = AutomationOccurrenceApplicationService(lambda: uow)

    with pytest.raises(RuntimeError, match="database write failed"):
        await service.execute_claimed(job=job, owner="worker")
    result = await service.record_failure(job=job, owner="worker")

    assert result is OccurrenceExecutionResult.RETRY_SCHEDULED
    assert occurrence.status is OccurrenceStatus.MATERIALIZED
    assert automation.status is AutomationStatus.ACTIVE
    uow.automations.update.assert_not_awaited()
    uow.durable_jobs.settle.assert_not_awaited()
    uow.durable_jobs.release_for_retry.assert_awaited_once()
    assert uow.rollbacks == 1
    assert uow.commits == 1


async def test_retry_exhaustion_marks_occurrence_and_job_failed() -> None:
    job, occurrence, automation = claimed_occurrence(attempt=5)
    uow = FakeUow(job, occurrence, automation)
    service = AutomationOccurrenceApplicationService(lambda: uow)

    result = await service.record_failure(job=job, owner="worker")

    assert result is OccurrenceExecutionResult.FAILED
    assert occurrence.status is OccurrenceStatus.FAILED
    assert automation.status is AutomationStatus.COMPLETED
    uow.durable_jobs.release_for_retry.assert_not_awaited()
    assert uow.durable_jobs.settle.call_args.kwargs["status"] is DurableJobStatus.FAILED
    assert uow.commits == 1
