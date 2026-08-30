from uuid import uuid4

import pytest

from laoshiren.application.memories.candidate import is_explicit_memory_command
from laoshiren.application.memories.formation import MemoryFormationEvent
from laoshiren.workers.memory import MemoryFormationWorker, tool_code_summary


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


class FakeDurableJobs:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, object]] = []

    async def get_by_dedupe_key(self, *, user_id, dedupe_key: str):
        del user_id, dedupe_key
        return None

    async def add(self, job) -> None:
        self.enqueued.append({"kind": job.kind, "payload": job.payload})

    async def claim_ready(self, **values):
        del values
        return []

    async def settle(self, **values) -> bool:
        del values
        return True


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.durable_jobs = FakeDurableJobs()
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        return None


def make_event() -> MemoryFormationEvent:
    return MemoryFormationEvent(
        user_id=uuid4(),
        run_id=uuid4(),
        thread_id=uuid4(),
        source_message_id=uuid4(),
        user_text="请记住：客户端用 ArkTS",
        tool_result_codes=("THING_CREATED", "DEADLINE_SET"),
    )


def test_explicit_memory_command_detection() -> None:
    assert is_explicit_memory_command("请记住：客户端用 ArkTS")
    assert is_explicit_memory_command("记住这个：预算 5000")
    assert not is_explicit_memory_command("今天天气怎么样")


def test_tool_code_summary_maps_to_chinese_action() -> None:
    assert tool_code_summary("THING_CREATED") == "创建了事务"
    assert tool_code_summary("DEADLINE_SET") == "设置了截止日期"
    assert tool_code_summary("UNKNOWN_CODE") == "UNKNOWN_CODE"


@pytest.mark.asyncio
async def test_worker_process_assembles_context_and_calls_manager() -> None:
    manager = FakeManager()
    uow = FakeUnitOfWork()
    worker = MemoryFormationWorker(
        manager,  # type: ignore[arg-type]
        FakeRuntime(),  # type: ignore[arg-type]
        lambda: uow,  # type: ignore[arg-type]
    )
    event = make_event()

    await worker.process(event)

    assert len(manager.calls) == 1
    call = manager.calls[0]
    assert call["user_id"] == event.user_id
    assert call["run_id"] == event.run_id
    assert call["source_message_id"] == event.source_message_id
    assert call["state_mutation_summaries"] == ("创建了事务", "设置了截止日期")
    assert call["recent_messages"] == ()


@pytest.mark.asyncio
async def test_enqueue_durable_writes_memory_formation_job() -> None:
    manager = FakeManager()
    uow = FakeUnitOfWork()
    worker = MemoryFormationWorker(
        manager,  # type: ignore[arg-type]
        FakeRuntime(),  # type: ignore[arg-type]
        lambda: uow,  # type: ignore[arg-type]
    )
    event = make_event()

    await worker.enqueue_durable(event)

    assert uow.committed is True
    assert len(uow.durable_jobs.enqueued) == 1
    payload = uow.durable_jobs.enqueued[0]["payload"]
    assert payload["run_id"] == str(event.run_id)
