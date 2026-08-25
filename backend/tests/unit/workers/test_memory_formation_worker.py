from uuid import uuid4

import pytest

from laoshiren.application.memories.candidate import is_explicit_memory_command
from laoshiren.workers.memory import (
    MemoryFormationEvent,
    MemoryFormationWorker,
    tool_code_summary,
)

pytestmark = pytest.mark.asyncio


class FakeManager:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def form_from_event(self, **values: object) -> tuple[object, ...]:
        self.calls.append(values)
        return ()


class FakeRuntime:
    async def list_messages(self, **values: object) -> list[object]:
        del values
        return []


def make_event() -> MemoryFormationEvent:
    return MemoryFormationEvent(
        user_id=uuid4(),
        run_id=uuid4(),
        thread_id=uuid4(),
        source_message_id=uuid4(),
        user_text="请记住：客户端用 ArkTS",
        tool_result_codes=("THING_CREATED", "DEADLINE_SET"),
    )


async def test_explicit_memory_command_detection() -> None:
    assert is_explicit_memory_command("请记住：客户端用 ArkTS")
    assert is_explicit_memory_command("记住这个：预算 5000")
    assert not is_explicit_memory_command("今天天气怎么样")


async def test_tool_code_summary_maps_to_chinese_action() -> None:
    assert tool_code_summary("THING_CREATED") == "创建了事务"
    assert tool_code_summary("DEADLINE_SET") == "设置了截止日期"
    assert tool_code_summary("UNKNOWN_CODE") == "UNKNOWN_CODE"


async def test_worker_process_assembles_context_and_calls_manager() -> None:
    manager = FakeManager()
    worker = MemoryFormationWorker(manager, FakeRuntime())  # type: ignore[arg-type]
    event = make_event()

    await worker.process(event)

    assert len(manager.calls) == 1
    call = manager.calls[0]
    assert call["user_id"] == event.user_id
    assert call["run_id"] == event.run_id
    assert call["source_message_id"] == event.source_message_id
    assert call["state_mutation_summaries"] == ("创建了事务", "设置了截止日期")
    assert call["recent_messages"] == ()


async def test_worker_drains_queue_with_run_once() -> None:
    manager = FakeManager()
    worker = MemoryFormationWorker(manager, FakeRuntime())  # type: ignore[arg-type]
    event = make_event()

    assert await worker.run_once() is False  # empty queue

    await worker.enqueue(event)
    assert await worker.run_once() is True
    assert len(manager.calls) == 1
    assert await worker.run_once() is False  # drained
