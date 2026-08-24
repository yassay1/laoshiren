import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from uuid import UUID

RunExecutor = Callable[..., Awaitable[object]]


class InProcessRunDispatcher:
    """V1 single-process queue; durable Run state remains in PostgreSQL."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[tuple[UUID, UUID]] = asyncio.Queue()
        self._consumer: asyncio.Task[None] | None = None

    async def dispatch(self, *, user_id: UUID, run_id: UUID) -> None:
        await self._queue.put((user_id, run_id))

    async def start(self, executor: RunExecutor) -> None:
        if self._consumer is not None:
            return

        async def consume() -> None:
            while True:
                user_id, run_id = await self._queue.get()
                try:
                    await executor(user_id=user_id, run_id=run_id)
                except Exception:
                    # AgentRunWorker persists FAILED before re-raising.
                    pass
                finally:
                    self._queue.task_done()

        self._consumer = asyncio.create_task(consume(), name="agent-run-consumer")

    async def stop(self) -> None:
        consumer = self._consumer
        self._consumer = None
        if consumer is None:
            return
        consumer.cancel()
        with suppress(asyncio.CancelledError):
            await consumer

    async def join(self) -> None:
        await self._queue.join()
