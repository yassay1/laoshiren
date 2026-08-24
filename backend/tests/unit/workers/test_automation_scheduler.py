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

    async def dispatch_pending(self, *, limit: int) -> int:
        assert limit == 7
        self.called.set()
        return 0


async def test_scheduler_runs_immediately_and_stops_cleanly() -> None:
    service = RecordingAutomationService()
    scheduler = AutomationScheduler(  # type: ignore[arg-type]
        service, interval_seconds=60, batch_size=7
    )

    await scheduler.start()
    await asyncio.wait_for(service.called.wait(), timeout=1)
    await scheduler.stop()

    assert service.calls == 1
