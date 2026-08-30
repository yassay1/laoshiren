import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from uuid import uuid4

from laoshiren.application.runtime.dto import DurableJobClaimDTO
from laoshiren.application.runtime.service import RuntimeApplicationService


class RunDispatchScanner:
    """Claims PostgreSQL AGENT_RUN jobs and executes them with fencing."""

    def __init__(
        self,
        service: RuntimeApplicationService,
        *,
        interval_seconds: float = 2.0,
        batch_size: int = 500,
        lease_seconds: float = 60.0,
    ) -> None:
        if interval_seconds <= 0 or batch_size <= 0 or lease_seconds <= 0:
            raise ValueError("Run scanner interval and batch size must be positive.")
        self._service = service
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._owner = f"run-job-worker-{uuid4()}"
        self._task: asyncio.Task[None] | None = None

    async def start(self, executor: Callable[..., Awaitable[object]]) -> None:
        if self._task is not None:
            return

        async def loop() -> None:
            while True:
                with suppress(Exception):
                    claims = await self._service.claim_agent_run_jobs(
                        owner=self._owner,
                        lease_seconds=self._lease_seconds,
                        limit=self._batch_size,
                    )
                    for claim in claims:
                        error_code: str | None = None
                        heartbeat = asyncio.create_task(
                            self._heartbeat(claim),
                            name=f"run-job-heartbeat-{claim.job_id}",
                        )
                        try:
                            await executor(user_id=claim.user_id, run_id=claim.run_id)
                        except Exception as exception:
                            error_code = type(exception).__name__
                        finally:
                            heartbeat.cancel()
                            with suppress(asyncio.CancelledError):
                                await heartbeat
                        await self._service.settle_agent_run_job(
                            claim=claim,
                            owner=self._owner,
                            error_code=error_code,
                        )
                await asyncio.sleep(self._interval_seconds)

        self._task = asyncio.create_task(loop(), name="run-dispatch-scanner")

    async def _heartbeat(self, claim: DurableJobClaimDTO) -> None:
        interval = max(0.1, self._lease_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            renewed = await self._service.renew_agent_run_job(
                claim=claim,
                owner=self._owner,
                lease_seconds=self._lease_seconds,
            )
            if not renewed:
                return

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
