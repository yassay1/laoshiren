"""Account deletion durable job worker."""

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from laoshiren.application.identity.service import apply_account_deletion
from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.application.runtime.durable_job_claim import claim_ready_jobs
from laoshiren.domain.runtime.entities import DurableJobKind, DurableJobStatus

UnitOfWorkFactory = Callable[[], PersonalStateUnitOfWork]


class AccountDeletionWorker:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        worker_id: str | None = None,
        lease_seconds: float = 60.0,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("Account deletion lease must be positive.")
        self._unit_of_work_factory = unit_of_work_factory
        self._worker_id = worker_id or f"account-deletion-{uuid4()}"
        self._lease_seconds = lease_seconds

    async def run_once(self) -> bool:
        now = datetime.now(UTC)
        async with self._unit_of_work_factory() as unit_of_work:
            jobs = await claim_ready_jobs(
                unit_of_work,
                kind=DurableJobKind.ACCOUNT_DELETION,
                owner=self._worker_id,
                now=now,
                lease_until=now + timedelta(seconds=self._lease_seconds),
                limit=1,
            )
            if not jobs:
                await unit_of_work.rollback()
                return False
            job = jobs[0]
            await apply_account_deletion(unit_of_work, user_id=job.user_id)
            settled = await unit_of_work.durable_jobs.settle(
                job_id=job.id,
                owner=self._worker_id,
                claim_epoch=job.claim_epoch,
                status=DurableJobStatus.COMPLETED,
                now=now,
            )
            if not settled:
                await unit_of_work.rollback()
                return False
            await unit_of_work.commit()
        return True


class AccountDeletionScheduler:
    def __init__(
        self,
        worker: AccountDeletionWorker,
        *,
        interval_seconds: float = 5.0,
        batch_size: int = 5,
    ) -> None:
        if interval_seconds <= 0 or batch_size <= 0:
            raise ValueError("Account deletion scheduler settings must be positive.")
        self._worker = worker
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._task: asyncio.Task[None] | None = None

    async def run_batch(self) -> int:
        processed = 0
        for _ in range(self._batch_size):
            if not await self._worker.run_once():
                break
            processed += 1
        return processed

    async def start(self) -> None:
        if self._task is not None:
            return

        async def loop() -> None:
            while True:
                with suppress(Exception):
                    await self.run_batch()
                await asyncio.sleep(self._interval_seconds)

        self._task = asyncio.create_task(loop(), name="account-deletion-scheduler")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
