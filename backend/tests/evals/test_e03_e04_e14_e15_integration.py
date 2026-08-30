"""Deterministic integration tests for PRD E03, E04, E14, and E15."""

import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest

from laoshiren.agent.contracts import DecisionKind, ExecutiveDecision, GraphState, ToolStatus
from laoshiren.bootstrap import build_agent_worker
from laoshiren.domain.memories.entities import MemoryType
from laoshiren.domain.personal_state.value_objects import TaskStatus
from laoshiren.domain.runtime.entities import RunStatus
from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.gate_d,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def upload_bytes(content: bytes) -> AsyncIterator[bytes]:
    yield content


class E03HearsayGateway:
    def __init__(self, *, thing_id: str, thing_version: int) -> None:
        self._thing_id = thing_id
        self._thing_version = thing_version
        self._attempted = False

    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
    ) -> ExecutiveDecision:
        if self._attempted or state.get("tool_results"):
            return ExecutiveDecision(
                DecisionKind.RESPOND,
                content="听说改期了，但我还没有可靠来源，暂未更新正式 deadline。",
            )
        self._attempted = True
        return ExecutiveDecision(
            DecisionKind.CALL_TOOL,
            tool_name="thing_date_set",
            tool_arguments={
                "thing_id": self._thing_id,
                "value": "2026-09-22T17:00:00+00:00",
                "timezone": "UTC",
                "certainty": "CONFIRMED",
                "expected_version": self._thing_version,
            },
        )


class E04MemoryRecallGateway:
    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
    ) -> ExecutiveDecision:
        memory = state.get("prefetched_state", {}).get("memory_context", {})
        profile = memory.get("profile", []) if isinstance(memory, dict) else []
        for item in profile:
            if isinstance(item, dict) and "简短中文" in str(item.get("content", "")):
                return ExecutiveDecision(
                    DecisionKind.RESPOND,
                    content="我们之前定的回复风格是简短中文。",
                )
        for result in state.get("tool_results", []):
            items = result.get("data", {}).get("items", [])
            for item in items:
                if isinstance(item, dict) and "简短中文" in str(item.get("content", "")):
                    return ExecutiveDecision(
                        DecisionKind.RESPOND,
                        content="我们之前定的回复风格是简短中文。",
                    )
        if state.get("tool_results"):
            return ExecutiveDecision(
                DecisionKind.RESPOND,
                content="没有找到相关记忆。",
            )
        return ExecutiveDecision(
            DecisionKind.CALL_TOOL,
            tool_name="memory_search",
            tool_arguments={"query": "回复风格", "memory_type": "PROFILE", "limit": 3},
        )


class E14StateAuthorityGateway:
    def __init__(self, *, thing_id: str) -> None:
        self._thing_id = thing_id
        self._loaded = False

    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
    ) -> ExecutiveDecision:
        if self._loaded or state.get("tool_results"):
            for result in state.get("tool_results", []):
                items = result.get("data", {}).get("items", [])
                if not items:
                    continue
                demo = next((item for item in items if item.get("title") == "Demo"), None)
                if demo is None:
                    continue
                if demo.get("status") == TaskStatus.TODO.value:
                    return ExecutiveDecision(
                        DecisionKind.RESPOND,
                        content="Demo 任务在 Personal State 里仍是 TODO，还没有完成。",
                    )
                return ExecutiveDecision(DecisionKind.RESPOND, content="已完成。")
            return ExecutiveDecision(
                DecisionKind.RESPOND,
                content="无法从 Personal State 确认任务状态。",
            )
        self._loaded = True
        return ExecutiveDecision(
            DecisionKind.CALL_TOOL,
            tool_name="state_get_thing_context",
            tool_arguments={"thing_id": self._thing_id},
        )


class E15SourceRetentionGateway:
    def __init__(self, *, source_id: str) -> None:
        self._source_id = source_id

    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
    ) -> ExecutiveDecision:
        if state.get("tool_results"):
            result = state["tool_results"][-1]
            data = result.get("data", {})
            if (
                result.get("status") == ToolStatus.SUCCESS.value
                and data.get("file_id") == self._source_id
                and data.get("mime_type")
            ):
                return ExecutiveDecision(
                    DecisionKind.RESPOND,
                    content="文件还在，原件 metadata 可读取。",
                )
            return ExecutiveDecision(DecisionKind.RESPOND, content="无法确认原件。")
        return ExecutiveDecision(
            DecisionKind.CALL_TOOL,
            tool_name="file_inspect",
            tool_arguments={"file_id": self._source_id},
        )


async def test_e03_hearsay_deadline_requires_verification() -> None:
    app = create_app()
    container = app.state.container
    user_id = UUID(container.settings.dev_user_id)
    await container.checkpoints.start()
    try:
        thing = await container.personal_state.create_thing(
            user_id=user_id,
            name="答辩准备",
            action_id="eval.e03",
            idempotency_key=f"e03-thing-{uuid4()}",
            reason="E03 setup",
        )
        thread = await container.runtime.create_thread(
            user_id=user_id,
            title="eval:E03",
            idempotency_key=f"e03-thread-{uuid4()}",
        )
        worker = build_agent_worker(
            container,
            E03HearsayGateway(thing_id=str(thing.id), thing_version=thing.version),
        )  # type: ignore[arg-type]
        run = await container.runtime.create_user_run(
            user_id=user_id,
            thread_id=thread.id,
            content="听说截止日期改到22号了。",
            source_ids=[],
            idempotency_key=f"e03-run-{uuid4()}",
        )
        status = await worker.run_once(user_id=user_id, run_id=run.id)
        assert status is RunStatus.COMPLETED
        refreshed = await container.personal_state.get_thing(user_id=user_id, thing_id=thing.id)
        assert refreshed.deadline_at is None
    finally:
        await container.checkpoints.stop()
        await container.database.dispose()


async def test_e04_cross_thread_profile_memory_recall() -> None:
    app = create_app()
    container = app.state.container
    user_id = UUID(container.settings.dev_user_id)
    await container.checkpoints.start()
    try:
        await container.memories.create(
            user_id=user_id,
            memory_type=MemoryType.PROFILE,
            content="用户希望助手用简短中文回答。",
            summary="回复风格",
            importance=0.9,
            confidence=1.0,
            idempotency_key=f"e04-memory-{uuid4()}",
        )
        thread_a = await container.runtime.create_thread(
            user_id=user_id,
            title="eval:E04-a",
            idempotency_key=f"e04-thread-a-{uuid4()}",
        )
        thread_b = await container.runtime.create_thread(
            user_id=user_id,
            title="eval:E04-b",
            idempotency_key=f"e04-thread-b-{uuid4()}",
        )
        assert thread_a.id != thread_b.id
        worker = build_agent_worker(container, E04MemoryRecallGateway())  # type: ignore[arg-type]
        run = await container.runtime.create_user_run(
            user_id=user_id,
            thread_id=thread_b.id,
            content="之前我们定的回复风格是什么？",
            source_ids=[],
            idempotency_key=f"e04-run-{uuid4()}",
        )
        status = await worker.run_once(user_id=user_id, run_id=run.id)
        assert status is RunStatus.COMPLETED
    finally:
        await container.checkpoints.stop()
        await container.database.dispose()


async def test_e14_state_overrides_memory_for_task_status() -> None:
    app = create_app()
    container = app.state.container
    user_id = UUID(container.settings.dev_user_id)
    await container.checkpoints.start()
    try:
        thing = await container.personal_state.create_thing(
            user_id=user_id,
            name="秋季 Demo",
            action_id="eval.e14",
            idempotency_key=f"e14-thing-{uuid4()}",
            reason="E14 setup",
        )
        await container.personal_state.create_task(
            user_id=user_id,
            thing_id=thing.id,
            title="Demo",
            action_id="eval.e14",
            idempotency_key=f"e14-task-{uuid4()}",
            reason="E14 setup",
        )
        await container.memories.create(
            user_id=user_id,
            memory_type=MemoryType.EPISODIC,
            content="Demo 任务已经完成了。",
            summary="Demo done memory",
            importance=0.5,
            confidence=0.6,
            idempotency_key=f"e14-memory-{uuid4()}",
        )
        thread = await container.runtime.create_thread(
            user_id=user_id,
            title="eval:E14",
            idempotency_key=f"e14-thread-{uuid4()}",
        )
        worker = build_agent_worker(container, E14StateAuthorityGateway(thing_id=str(thing.id)))  # type: ignore[arg-type]
        run = await container.runtime.create_user_run(
            user_id=user_id,
            thread_id=thread.id,
            content="那个任务完成了吗？",
            source_ids=[],
            idempotency_key=f"e14-run-{uuid4()}",
        )
        status = await worker.run_once(user_id=user_id, run_id=run.id)
        assert status is RunStatus.COMPLETED
    finally:
        await container.checkpoints.stop()
        await container.database.dispose()


async def test_e15_source_get_preserves_artifact_metadata() -> None:
    app = create_app()
    container = app.state.container
    user_id = UUID(container.settings.dev_user_id)
    await container.checkpoints.start()
    try:
        uploaded = await container.sources.upload(
            user_id=user_id,
            filename="brief.txt",
            mime_type="text/plain",
            chunks=upload_bytes(b"project brief content"),
            idempotency_key=f"e15-source-{uuid4()}",
        )
        thread = await container.runtime.create_thread(
            user_id=user_id,
            title="eval:E15",
            idempotency_key=f"e15-thread-{uuid4()}",
        )
        worker = build_agent_worker(
            container, E15SourceRetentionGateway(source_id=str(uploaded.id))
        )  # type: ignore[arg-type]
        run = await container.runtime.create_user_run(
            user_id=user_id,
            thread_id=thread.id,
            content="我上传的文件还在吗？",
            source_ids=[],
            idempotency_key=f"e15-run-{uuid4()}",
        )
        status = await worker.run_once(user_id=user_id, run_id=run.id)
        assert status is RunStatus.COMPLETED
    finally:
        await container.checkpoints.stop()
        await container.database.dispose()
