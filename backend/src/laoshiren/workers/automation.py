import asyncio
from contextlib import suppress

from laoshiren.application.automations.service import AutomationApplicationService
from laoshiren.workers.automation_occurrence import AutomationOccurrenceWorker
from laoshiren.workers.push_delivery import PushDeliveryWorker


async def run_once(
    service: AutomationApplicationService,
    occurrence_worker: AutomationOccurrenceWorker,
    push_worker: PushDeliveryWorker,
    *,
    limit: int = 100,
) -> tuple[int, int]:
    generated = await service.process_due(limit=limit)
    processed = 0
    for _ in range(limit):
        if not await occurrence_worker.run_once():
            break
        processed += 1
    for _ in range(limit):
        if not await push_worker.run_once():
            break
        processed += 1
    return generated, processed


class AutomationScheduler:
    """Small persistent-state scheduler; database state survives process restarts."""

    def __init__(
        self,
        service: AutomationApplicationService,
        occurrence_worker: AutomationOccurrenceWorker,
        push_worker: PushDeliveryWorker,
        *,
        interval_seconds: float = 30.0,
        batch_size: int = 100,
    ) -> None:
        self._service = service
        self._occurrence_worker = occurrence_worker
        self._push_worker = push_worker
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return

        async def loop() -> None:
            while True:
                with suppress(Exception):
                    await run_once(
                        self._service,
                        self._occurrence_worker,
                        self._push_worker,
                        limit=self._batch_size,
                    )
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
