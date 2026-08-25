import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from uuid import UUID

from laoshiren.application.memories.manager import MemoryManager
from laoshiren.application.runtime.service import RuntimeApplicationService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MemoryFormationEvent:
    """A durable-free signal that a Run finished and memory formation is due."""

    user_id: UUID
    run_id: UUID
    thread_id: UUID
    source_message_id: UUID
    user_text: str
    tool_result_codes: tuple[str, ...] = field(default_factory=tuple)


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
    """Drains formation events and runs the LLM Memory Manager in the background."""

    def __init__(
        self,
        manager: MemoryManager,
        runtime: RuntimeApplicationService,
        *,
        interval_seconds: float = 2.0,
        batch_size: int = 10,
    ) -> None:
        if interval_seconds <= 0 or batch_size <= 0:
            raise ValueError("Memory formation interval and batch size must be positive.")
        self._manager = manager
        self._runtime = runtime
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._queue: asyncio.Queue[MemoryFormationEvent] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def enqueue(self, event: MemoryFormationEvent) -> None:
        await self._queue.put(event)

    async def process(self, event: MemoryFormationEvent) -> None:
        """Run formation for one event now (explicit-command hot path or queue drain)."""
        try:
            await self._process(event)
        except Exception:
            logger.exception(
                "memory_formation_failed",
                extra={"run_id": str(event.run_id), "user_id": str(event.user_id)},
            )

    async def run_once(self) -> bool:
        try:
            event = self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return False
        try:
            await self._process(event)
        finally:
            self._queue.task_done()
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
