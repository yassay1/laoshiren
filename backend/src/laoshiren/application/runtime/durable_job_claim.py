"""Shared durable job claim path with expired-lease recovery."""

from datetime import datetime
from typing import Protocol

from laoshiren.application.runtime.ports import DurableJobRepository
from laoshiren.domain.runtime.entities import DurableJob, DurableJobKind


class DurableJobUnitOfWork(Protocol):
    durable_jobs: DurableJobRepository


async def claim_ready_jobs(
    unit_of_work: DurableJobUnitOfWork,
    *,
    kind: DurableJobKind,
    owner: str,
    now: datetime,
    lease_until: datetime,
    limit: int,
) -> list[DurableJob]:
    await unit_of_work.durable_jobs.requeue_expired(now=now)
    return await unit_of_work.durable_jobs.claim_ready(
        kind=kind,
        owner=owner,
        now=now,
        lease_until=lease_until,
        limit=limit,
    )
