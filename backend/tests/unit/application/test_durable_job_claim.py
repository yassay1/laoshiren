from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from laoshiren.application.runtime.durable_job_claim import claim_ready_jobs
from laoshiren.domain.runtime.entities import DurableJob, DurableJobKind


@pytest.mark.asyncio
async def test_claim_ready_jobs_requeues_expired_before_claim() -> None:
    now = datetime.now(UTC)
    job = DurableJob(
        user_id=uuid4(),
        kind=DurableJobKind.FILE_PURGE,
        dedupe_key="file-purge:test",
        payload={"file_id": str(uuid4())},
        available_at=now,
    )
    durable_jobs = AsyncMock()
    durable_jobs.requeue_expired = AsyncMock(return_value=1)
    durable_jobs.claim_ready = AsyncMock(return_value=[job])
    unit_of_work = AsyncMock()
    unit_of_work.durable_jobs = durable_jobs

    result = await claim_ready_jobs(
        unit_of_work,
        kind=DurableJobKind.FILE_PURGE,
        owner="worker-1",
        now=now,
        lease_until=now + timedelta(seconds=60),
        limit=1,
    )

    durable_jobs.requeue_expired.assert_awaited_once_with(now=now)
    durable_jobs.claim_ready.assert_awaited_once()
    assert result == [job]
