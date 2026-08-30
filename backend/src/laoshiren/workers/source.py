import asyncio
from contextlib import suppress
from uuid import uuid4

from laoshiren.application.sources.ports import SourceParsingError
from laoshiren.application.sources.service import SourceApplicationService


class SourceProcessingWorker:
    """Claims and parses one durable Source without owning persistence details."""

    def __init__(
        self,
        service: SourceApplicationService,
        *,
        worker_id: str | None = None,
        lease_seconds: float = 60.0,
        heartbeat_seconds: float = 15.0,
        max_attempts: int = 3,
        retry_base_seconds: float = 5.0,
        retry_max_seconds: float = 300.0,
    ) -> None:
        if lease_seconds <= 0 or not 0 < heartbeat_seconds < lease_seconds:
            raise ValueError("Source heartbeat must be positive and shorter than its lease.")
        if max_attempts <= 0 or retry_base_seconds <= 0 or retry_max_seconds <= 0:
            raise ValueError("Source retry settings must be positive.")
        self._service = service
        self._worker_id = worker_id or f"source-worker-{uuid4()}"
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds

    async def run_once(self) -> bool:
        job = await self._service.claim_next_processing(
            owner=self._worker_id,
            lease_seconds=self._lease_seconds,
            max_attempts=self._max_attempts,
        )
        if job is None:
            return False

        lease_lost = asyncio.Event()

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(self._heartbeat_seconds)
                renewed = await self._service.renew_processing_lease(
                    source_id=job.id,
                    owner=self._worker_id,
                    lease_seconds=self._lease_seconds,
                )
                if not renewed:
                    lease_lost.set()
                    return

        heartbeat_task = asyncio.create_task(heartbeat(), name=f"source-heartbeat-{job.id}")
        try:
            parsed_content = await self._service.extract_claimed_content(job)
            if lease_lost.is_set():
                return True
            await self._service.complete_processing(
                source_id=job.id,
                owner=self._worker_id,
                parsed_content=parsed_content,
            )
        except SourceParsingError:
            await self._service.fail_processing(
                source_id=job.id,
                owner=self._worker_id,
                error_code="SOURCE_PARSE_FAILED",
                retry_delay_seconds=None,
            )
        except Exception:
            exhausted = job.attempt_count >= self._max_attempts
            delay = min(
                self._retry_base_seconds * (2 ** max(job.attempt_count - 1, 0)),
                self._retry_max_seconds,
            )
            await self._service.fail_processing(
                source_id=job.id,
                owner=self._worker_id,
                error_code=(
                    "SOURCE_PROCESSING_EXHAUSTED" if exhausted else "SOURCE_PROCESSING_RETRYABLE"
                ),
                retry_delay_seconds=None if exhausted else delay,
            )
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
        return True


class SourceProcessingScheduler:
    """Continuously drains durable Source work in bounded batches."""

    def __init__(
        self,
        worker: SourceProcessingWorker,
        *,
        interval_seconds: float = 2.0,
        batch_size: int = 10,
    ) -> None:
        if interval_seconds <= 0 or batch_size <= 0:
            raise ValueError("Source scheduler interval and batch size must be positive.")
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

        self._task = asyncio.create_task(loop(), name="source-processing-scheduler")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
