import asyncio
from contextlib import suppress

from laoshiren.application.runtime.service import RuntimeApplicationService


class RunDispatchScanner:
    """Periodically wakes durable Runs; database claims still own execution."""

    def __init__(
        self,
        service: RuntimeApplicationService,
        *,
        interval_seconds: float = 2.0,
        batch_size: int = 500,
    ) -> None:
        if interval_seconds <= 0 or batch_size <= 0:
            raise ValueError("Run scanner interval and batch size must be positive.")
        self._service = service
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return

        async def loop() -> None:
            while True:
                # A failed scan must not terminate future database recovery ticks.
                with suppress(Exception):
                    await self._service.recover_pending_runs(limit=self._batch_size)
                await asyncio.sleep(self._interval_seconds)

        self._task = asyncio.create_task(loop(), name="run-dispatch-scanner")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
