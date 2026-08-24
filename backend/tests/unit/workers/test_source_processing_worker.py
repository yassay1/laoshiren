from uuid import uuid4

import pytest

from laoshiren.application.sources.dto import SourceProcessingJobDTO
from laoshiren.application.sources.ports import SourceParsingError
from laoshiren.workers.source import SourceProcessingScheduler, SourceProcessingWorker

pytestmark = pytest.mark.asyncio


class RecordingSourceService:
    def __init__(
        self,
        *,
        jobs: list[SourceProcessingJobDTO],
        extracted_text: str = "parsed",
        error: Exception | None = None,
    ) -> None:
        self.jobs = jobs
        self.extracted_text = extracted_text
        self.error = error
        self.completed: list[tuple[object, str, str]] = []
        self.failed: list[tuple[object, str, str, float | None]] = []

    async def claim_next_processing(
        self, *, owner: str, lease_seconds: float, max_attempts: int
    ) -> SourceProcessingJobDTO | None:
        assert owner == "worker-a"
        assert lease_seconds == 60
        assert max_attempts == 3
        return self.jobs.pop(0) if self.jobs else None

    async def extract_claimed_text(self, job: SourceProcessingJobDTO) -> str:
        if self.error is not None:
            raise self.error
        return self.extracted_text

    async def renew_processing_lease(
        self, *, source_id: object, owner: str, lease_seconds: float
    ) -> bool:
        return True

    async def complete_processing(
        self, *, source_id: object, owner: str, extracted_text: str
    ) -> bool:
        self.completed.append((source_id, owner, extracted_text))
        return True

    async def fail_processing(
        self,
        *,
        source_id: object,
        owner: str,
        error_code: str,
        retry_delay_seconds: float | None,
    ) -> bool:
        self.failed.append((source_id, owner, error_code, retry_delay_seconds))
        return True


def job(*, attempt_count: int = 1) -> SourceProcessingJobDTO:
    return SourceProcessingJobDTO(
        id=uuid4(),
        user_id=uuid4(),
        title="notes.md",
        mime_type="text/markdown",
        object_key="object.md",
        attempt_count=attempt_count,
    )


async def test_worker_completes_claimed_source() -> None:
    claimed = job()
    service = RecordingSourceService(jobs=[claimed])
    worker = SourceProcessingWorker(  # type: ignore[arg-type]
        service, worker_id="worker-a"
    )

    assert await worker.run_once() is True
    assert service.completed == [(claimed.id, "worker-a", "parsed")]
    assert service.failed == []


async def test_deterministic_parse_failure_is_terminal() -> None:
    claimed = job()
    service = RecordingSourceService(
        jobs=[claimed], error=SourceParsingError("invalid pdf")
    )
    worker = SourceProcessingWorker(  # type: ignore[arg-type]
        service, worker_id="worker-a"
    )

    await worker.run_once()

    assert service.failed == [
        (claimed.id, "worker-a", "SOURCE_PARSE_FAILED", None)
    ]


async def test_transient_failure_uses_bounded_exponential_retry() -> None:
    claimed = job(attempt_count=2)
    service = RecordingSourceService(jobs=[claimed], error=OSError("storage unavailable"))
    worker = SourceProcessingWorker(  # type: ignore[arg-type]
        service,
        worker_id="worker-a",
        retry_base_seconds=7,
        retry_max_seconds=10,
    )

    await worker.run_once()

    assert service.failed == [
        (claimed.id, "worker-a", "SOURCE_PROCESSING_RETRYABLE", 10)
    ]


async def test_last_attempt_becomes_terminal() -> None:
    claimed = job(attempt_count=3)
    service = RecordingSourceService(jobs=[claimed], error=OSError("still unavailable"))
    worker = SourceProcessingWorker(  # type: ignore[arg-type]
        service, worker_id="worker-a"
    )

    await worker.run_once()

    assert service.failed == [
        (claimed.id, "worker-a", "SOURCE_PROCESSING_EXHAUSTED", None)
    ]


async def test_scheduler_drains_only_configured_batch() -> None:
    service = RecordingSourceService(jobs=[job(), job(), job()])
    worker = SourceProcessingWorker(  # type: ignore[arg-type]
        service, worker_id="worker-a"
    )
    scheduler = SourceProcessingScheduler(worker, batch_size=2)

    assert await scheduler.run_batch() == 2
    assert len(service.jobs) == 1
