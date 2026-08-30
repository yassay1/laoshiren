import asyncio

import pytest

from laoshiren.workers.automation import AutomationScheduler

pytestmark = pytest.mark.asyncio


class RecordingAutomationService:
    def __init__(self) -> None:
        self.calls = 0
        self.called = asyncio.Event()

    async def process_due(self, *, limit: int) -> int:
        assert limit == 7
        self.calls += 1
        return 0


class NoopWorker:
    async def run_once(self) -> bool:
        return False


async def test_scheduler_runs_immediately_and_stops_cleanly() -> None:
    service = RecordingAutomationService()
    scheduler = AutomationScheduler(  # type: ignore[arg-type]
        service,
        NoopWorker(),  # type: ignore[arg-type]
        NoopWorker(),  # type: ignore[arg-type]
        interval_seconds=60,
        batch_size=7,
    )

    await scheduler.start()
    await asyncio.sleep(0.05)
    await scheduler.stop()

    assert service.calls >= 1
