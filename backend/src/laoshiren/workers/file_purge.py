"""Physical purge worker for deleted Files."""

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from laoshiren.application.files.purge import apply_physical_purge
from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.application.runtime.durable_job_claim import claim_ready_jobs
from laoshiren.application.sources.ports import ObjectStorage
from laoshiren.domain.runtime.entities import DurableJobKind, DurableJobStatus

UnitOfWorkFactory = Callable[[], PersonalStateUnitOfWork]


class FilePurgeWorker:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        storage: ObjectStorage,
        *,
        worker_id: str | None = None,
        lease_seconds: float = 60.0,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("File purge lease must be positive.")
        self._unit_of_work_factory = unit_of_work_factory
        self._storage = storage
        self._worker_id = worker_id or f"file-purge-{uuid4()}"
        self._lease_seconds = lease_seconds

    async def run_once(self) -> bool:
        now = datetime.now(UTC)
        async with self._unit_of_work_factory() as unit_of_work:
            jobs = await claim_ready_jobs(
                unit_of_work,
                kind=DurableJobKind.FILE_PURGE,
                owner=self._worker_id,
                now=now,
                lease_until=now + timedelta(seconds=self._lease_seconds),
                limit=1,
            )
            if not jobs:
                await unit_of_work.rollback()
                return False
            job = jobs[0]
            file_id = UUID(str(job.payload["file_id"]))
            object_key = await apply_physical_purge(
                unit_of_work,
                user_id=job.user_id,
                file_id=file_id,
            )
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
        if object_key:
            await self._storage.delete(object_key=object_key)
        return True

    async def scan_orphan_storage(self, *, limit: int = 20) -> int:
        if not hasattr(self._storage, "list_object_keys"):
            return 0
        list_keys = self._storage.list_object_keys
        async with self._unit_of_work_factory() as unit_of_work:
            known = set(await unit_of_work.files.list_storage_keys())
            await unit_of_work.rollback()
        removed = 0
        for key in await list_keys():
            if key in known or key.endswith(".uploading"):
                continue
            await self._storage.delete(object_key=key)
            removed += 1
            if removed >= limit:
                break
        return removed


class FilePurgeScheduler:
    def __init__(
        self,
        worker: FilePurgeWorker,
        *,
        interval_seconds: float = 5.0,
        batch_size: int = 5,
    ) -> None:
        if interval_seconds <= 0 or batch_size <= 0:
            raise ValueError("File purge scheduler settings must be positive.")
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
        with suppress(Exception):
            await self._worker.scan_orphan_storage()
        return processed

    async def start(self) -> None:
        if self._task is not None:
            return

        async def loop() -> None:
            while True:
                with suppress(Exception):
                    await self.run_batch()
                await asyncio.sleep(self._interval_seconds)

        self._task = asyncio.create_task(loop(), name="file-purge-scheduler")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
