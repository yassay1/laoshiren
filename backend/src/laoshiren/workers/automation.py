import asyncio
from contextlib import suppress

from laoshiren.application.automations.service import AutomationApplicationService


async def run_once(service: AutomationApplicationService, *, limit: int = 100) -> tuple[int, int]:
    generated = await service.process_due(limit=limit)
    submitted = await service.dispatch_pending(limit=limit)
    return generated, submitted


class AutomationScheduler:
    """Small persistent-state scheduler; database state survives process restarts."""

    def __init__(
        self,
        service: AutomationApplicationService,
        *,
        interval_seconds: float = 30.0,
        batch_size: int = 100,
    ) -> None:
        self._service = service
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return

        async def loop() -> None:
            while True:
                # Individual failures remain durable and are retried on a later tick.
                with suppress(Exception):
                    await run_once(self._service, limit=self._batch_size)
                await asyncio.sleep(self._interval_seconds)

        self._task = asyncio.create_task(loop(), name="automation-scheduler")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
