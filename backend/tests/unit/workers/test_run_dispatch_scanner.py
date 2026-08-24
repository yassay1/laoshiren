import asyncio

import pytest

from laoshiren.workers.runtime import RunDispatchScanner

pytestmark = pytest.mark.asyncio


class RecordingRuntimeService:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.calls = 0
        self.fail_first = fail_first
        self.called = asyncio.Event()

    async def recover_pending_runs(self, *, limit: int) -> int:
        assert limit == 7
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise RuntimeError("temporary database outage")
        self.called.set()
        return 0


async def test_scanner_runs_immediately_and_stops_cleanly() -> None:
    service = RecordingRuntimeService()
    scanner = RunDispatchScanner(  # type: ignore[arg-type]
        service, interval_seconds=60, batch_size=7
    )

    await scanner.start()
    await asyncio.wait_for(service.called.wait(), timeout=1)
    await scanner.stop()

    assert service.calls == 1


async def test_scanner_survives_a_failed_tick() -> None:
    service = RecordingRuntimeService(fail_first=True)
    scanner = RunDispatchScanner(  # type: ignore[arg-type]
        service, interval_seconds=0.01, batch_size=7
    )

    await scanner.start()
    await asyncio.wait_for(service.called.wait(), timeout=1)
    await scanner.stop()

    assert service.calls >= 2


async def test_scanner_start_is_idempotent() -> None:
    service = RecordingRuntimeService()
    scanner = RunDispatchScanner(  # type: ignore[arg-type]
        service, interval_seconds=60, batch_size=7
    )

    await scanner.start()
    await scanner.start()
    await asyncio.wait_for(service.called.wait(), timeout=1)
    await scanner.stop()

    assert service.calls == 1
