"""Deterministic integration tests for PRD E05, E06, and E13."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from laoshiren.agent.contracts import DecisionKind, ExecutiveDecision, GraphState
from laoshiren.bootstrap import build_agent_worker
from laoshiren.domain.personal_state.value_objects import DateCertainty
from laoshiren.domain.runtime.entities import RunStatus
from laoshiren.domain.sources.entities import SourceRelationType
from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def upload_bytes(content: bytes) -> AsyncIterator[bytes]:
    yield content


class E05LinkSourceGateway:
    def __init__(self, *, thing_id: str, source_id: str) -> None:
        self._thing_id = thing_id
        self._source_id = source_id
        self._linked = False

    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
    ) -> ExecutiveDecision:
        if self._linked or state.get("tool_results"):
            return ExecutiveDecision(DecisionKind.RESPOND, content="资料已关联到项目。")
        self._linked = True
        return ExecutiveDecision(
            DecisionKind.CALL_TOOL,
            tool_name="source.link_thing",
            tool_arguments={
                "thing_id": self._thing_id,
                "source_id": self._source_id,
                "reason": "E05 eval link",
            },
        )


class E06SourceDeadlineGateway:
    def __init__(
        self,
        *,
        thing_id: str,
        thing_version: int,
        source_id: str,
        deadline_value: str,
    ) -> None:
        self._thing_id = thing_id
        self._thing_version = thing_version
        self._source_id = source_id
        self._deadline_value = deadline_value
        self._set = False

    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
    ) -> ExecutiveDecision:
        if self._set or state.get("tool_results"):
            return ExecutiveDecision(
                DecisionKind.RESPOND,
                content="已根据附件中的正式 deadline 更新。",
            )
        self._set = True
        return ExecutiveDecision(
            DecisionKind.CALL_TOOL,
            tool_name="state.set_deadline",
            tool_arguments={
                "thing_id": self._thing_id,
                "value": self._deadline_value,
                "timezone": "UTC",
                "certainty": "CONFIRMED",
                "expected_version": self._thing_version,
                "source_id": self._source_id,
                "reason": "E06 source evidence",
            },
        )


class E13AmbiguousGateway:
    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
    ) -> ExecutiveDecision:
        prefetch = state.get("prefetched_state", {}).get("active_thing_context", {})
        if prefetch.get("match_status") == "ambiguous":
            return ExecutiveDecision(
                DecisionKind.ASK_USER,
                prompt={"type": "input", "message": "你有多个 Demo 项目，请说明是哪一个。"},
            )
        return ExecutiveDecision(DecisionKind.RESPOND, content="已处理。")


async def test_e05_source_link_via_agent_tool() -> None:
    """E05: Agent can associate a Source with a Thing and preserve the link."""
    app = create_app()
    container = app.state.container
    user_id = UUID(container.settings.dev_user_id)
    await container.checkpoints.start()
    try:
        thing = await container.personal_state.create_thing(
            user_id=user_id,
            name="秋季比赛",
            action_id="eval.e05",
            idempotency_key=f"e05-thing-{uuid4()}",
            reason="E05 setup",
        )
        uploaded = await container.sources.upload(
            user_id=user_id,
            filename="brief.txt",
            mime_type="text/plain",
            chunks=upload_bytes(b"project brief"),
            idempotency_key=f"e05-source-{uuid4()}",
        )
        thread = await container.runtime.create_thread(
            user_id=user_id,
            title="eval:E05",
            idempotency_key=f"e05-thread-{uuid4()}",
        )
        gateway = E05LinkSourceGateway(
            thing_id=str(thing.id),
            source_id=str(uploaded.id),
        )
        worker = build_agent_worker(container, gateway)  # type: ignore[arg-type]
        run = await container.runtime.create_user_run(
            user_id=user_id,
            thread_id=thread.id,
            content="请把这份资料关联到当前项目。",
            source_ids=[uploaded.id],
            idempotency_key=f"e05-run-{uuid4()}",
        )
        status = await worker.run_once(user_id=user_id, run_id=run.id)
        assert status is RunStatus.COMPLETED
        linked = await container.sources.list_for_thing(
            user_id=user_id, thing_id=thing.id
        )
        assert any(item.id == uploaded.id for item in linked)
    finally:
        await container.checkpoints.stop()
        await container.database.dispose()


async def test_e06_deadline_from_source_evidence_uses_confirmed_policy() -> None:
    """E06: formal deadline from Source evidence must use CONFIRMED certainty."""
    app = create_app()
    container = app.state.container
    user_id = UUID(container.settings.dev_user_id)
    deadline_value = datetime(2026, 9, 22, 17, 0, tzinfo=UTC)
    await container.checkpoints.start()
    try:
        thing = await container.personal_state.create_thing(
            user_id=user_id,
            name="答辩准备",
            action_id="eval.e06",
            idempotency_key=f"e06-thing-{uuid4()}",
            reason="E06 setup",
        )
        uploaded = await container.sources.upload(
            user_id=user_id,
            filename="notice.txt",
            mime_type="text/plain",
            chunks=upload_bytes(b"Official deadline: 2026-09-22 17:00 UTC"),
            idempotency_key=f"e06-source-{uuid4()}",
        )
        await container.sources.link_to_thing(
            user_id=user_id,
            thing_id=thing.id,
            source_id=uploaded.id,
            relation_type=SourceRelationType.EVIDENCE,
            relevance=1.0,
            action_id="eval.e06.link",
            idempotency_key=f"e06-link-{uuid4()}",
            reason="E06 setup",
        )
        thread = await container.runtime.create_thread(
            user_id=user_id,
            title="eval:E06",
            active_thing_id=thing.id,
            idempotency_key=f"e06-thread-{uuid4()}",
        )
        gateway = E06SourceDeadlineGateway(
            thing_id=str(thing.id),
            thing_version=thing.version,
            source_id=str(uploaded.id),
            deadline_value=deadline_value.isoformat(),
        )
        worker = build_agent_worker(container, gateway)  # type: ignore[arg-type]
        run = await container.runtime.create_user_run(
            user_id=user_id,
            thread_id=thread.id,
            content="根据附件里的正式 deadline 更新。",
            source_ids=[uploaded.id],
            idempotency_key=f"e06-run-{uuid4()}",
        )
        status = await worker.run_once(user_id=user_id, run_id=run.id)
        assert status is RunStatus.COMPLETED
        refreshed = await container.personal_state.get_thing(
            user_id=user_id, thing_id=thing.id
        )
        assert refreshed.deadline_at == deadline_value
        dates = await container.personal_state.get_dates(
            user_id=user_id, thing_id=thing.id
        )
        primary = next(item for item in dates if item.is_primary)
        assert primary.certainty is DateCertainty.CONFIRMED
        assert primary.source_id == uploaded.id
    finally:
        await container.checkpoints.stop()
        await container.database.dispose()


async def test_e13_ambiguous_demo_completion_requests_clarification() -> None:
    app = create_app()
    container = app.state.container
    user_id = UUID(container.settings.dev_user_id)
    await container.checkpoints.start()
    try:
        for suffix in ("A", "B"):
            await container.personal_state.create_thing(
                user_id=user_id,
                name=f"Demo {suffix}",
                action_id="eval.e13",
                idempotency_key=f"e13-thing-{suffix}-{uuid4()}",
                reason="E13 setup",
            )
        thread = await container.runtime.create_thread(
            user_id=user_id,
            title="eval:E13",
            idempotency_key=f"e13-thread-{uuid4()}",
        )
        worker = build_agent_worker(container, E13AmbiguousGateway())  # type: ignore[arg-type]
        run = await container.runtime.create_user_run(
            user_id=user_id,
            thread_id=thread.id,
            content="帮我把 Demo 标记完成。",
            source_ids=[],
            idempotency_key=f"e13-run-{uuid4()}",
        )
        status = await worker.run_once(user_id=user_id, run_id=run.id)
        assert status is RunStatus.WAITING_USER
    finally:
        await container.checkpoints.stop()
        await container.database.dispose()
