import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from laoshiren.application.memories.formation import (
    MemoryFormationEvent,
    enqueue_memory_formation,
    event_from_job_payload,
)
from laoshiren.application.memories.manager import MemoryManager
from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.application.runtime.durable_job_claim import claim_ready_jobs
from laoshiren.application.runtime.service import RuntimeApplicationService
from laoshiren.domain.runtime.entities import DurableJobKind, DurableJobStatus

logger = logging.getLogger(__name__)

UnitOfWorkFactory = Callable[[], PersonalStateUnitOfWork]

_TOOL_CODE_SUMMARIES = {
    "THING_CREATED": "创建了事务",
    "THING_UPDATED": "更新了事务",
    "THING_ARCHIVED": "归档了事务",
    "TASK_CREATED": "创建了任务",
    "TASK_COMPLETED": "完成了任务",
    "TASK_STATUS_CHANGED": "变更了任务状态",
    "DEADLINE_SET": "设置了截止日期",
    "DATE_UPDATED": "更新了日期",
    "BLOCKER_ADDED": "添加了阻碍",
    "BLOCKER_RESOLVED": "解决了阻碍",
    "AUTOMATION_CREATED": "创建了自动化",
    "AUTOMATION_CHANGED": "变更了自动化",
}


def tool_code_summary(code: str) -> str:
    return _TOOL_CODE_SUMMARIES.get(code, code)


class MemoryFormationWorker:
    """Claims MEMORY_FORMATION durable jobs and runs the LLM Memory Manager."""

    def __init__(
        self,
        manager: MemoryManager,
        runtime: RuntimeApplicationService,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        worker_id: str | None = None,
        interval_seconds: float = 2.0,
        batch_size: int = 10,
        lease_seconds: float = 120.0,
    ) -> None:
        if interval_seconds <= 0 or batch_size <= 0 or lease_seconds <= 0:
            raise ValueError("Memory formation worker settings must be positive.")
        self._manager = manager
        self._runtime = runtime
        self._unit_of_work_factory = unit_of_work_factory
        self._worker_id = worker_id or f"memory-formation-{uuid4()}"
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._task: asyncio.Task[None] | None = None

    async def enqueue_durable(self, event: MemoryFormationEvent) -> None:
        async with self._unit_of_work_factory() as unit_of_work:
            await enqueue_memory_formation(unit_of_work, user_id=event.user_id, event=event)
            await unit_of_work.commit()

    async def process(self, event: MemoryFormationEvent) -> None:
        """Run formation for one event now (explicit-command hot path)."""
        try:
            await self._process(event)
        except Exception:
            logger.exception(
                "memory_formation_failed",
                extra={"run_id": str(event.run_id), "user_id": str(event.user_id)},
            )

    async def run_once(self) -> bool:
        now = datetime.now(UTC)
        async with self._unit_of_work_factory() as unit_of_work:
            jobs = await claim_ready_jobs(
                unit_of_work,
                kind=DurableJobKind.MEMORY_FORMATION,
                owner=self._worker_id,
                now=now,
                lease_until=now + timedelta(seconds=self._lease_seconds),
                limit=1,
            )
            if not jobs:
                await unit_of_work.rollback()
                return False
            job = jobs[0]
            await unit_of_work.commit()

        event = event_from_job_payload(user_id=job.user_id, payload=job.payload)
        try:
            await self._process(event)
        except Exception:
            logger.exception(
                "memory_formation_failed",
                extra={"run_id": str(event.run_id), "user_id": str(event.user_id)},
            )

        async with self._unit_of_work_factory() as unit_of_work:
            settled = await unit_of_work.durable_jobs.settle(
                job_id=job.id,
                owner=self._worker_id,
                claim_epoch=job.claim_epoch,
                status=DurableJobStatus.COMPLETED,
                now=datetime.now(UTC),
            )
            if settled:
                await unit_of_work.commit()
            else:
                await unit_of_work.rollback()
        return True

    async def _process(self, event: MemoryFormationEvent) -> None:
        messages = await self._runtime.list_messages(
            user_id=event.user_id, thread_id=event.thread_id, limit=10
        )
        recent = tuple(message.content for message in messages)
        summaries = tuple(tool_code_summary(code) for code in event.tool_result_codes)
        await self._manager.form_from_event(
            user_id=event.user_id,
            run_id=event.run_id,
            source_message_id=event.source_message_id,
            user_text=event.user_text,
            recent_messages=recent,
            state_mutation_summaries=summaries,
        )

    async def start(self) -> None:
        if self._task is not None:
            return

        async def loop() -> None:
            while True:
                with suppress(Exception):
                    for _ in range(self._batch_size):
                        if not await self.run_once():
                            break
                await asyncio.sleep(self._interval_seconds)

        self._task = asyncio.create_task(loop(), name="memory-formation-worker")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
