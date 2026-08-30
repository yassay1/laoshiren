import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from laoshiren.agent.contracts import DecisionKind, ExecutiveDecision, GraphState
from laoshiren.bootstrap import build_agent_worker
from laoshiren.domain.runtime.entities import RunEventType, RunStatus
from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


class WorkerGateway:
    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
    ) -> ExecutiveDecision:
        assert "state_get_thing_context" in available_tools
        assert "thing_date_set" in available_tools
        assert "state_get_thing_context" in tool_manifest
        return ExecutiveDecision(
            DecisionKind.RESPOND,
            content=f"已处理：{state['current_input']}",
        )


class NeverCalledGateway:
    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
    ) -> ExecutiveDecision:
        raise AssertionError("Recovery must finalize persisted terminal output.")


async def test_worker_completes_persistent_run_and_emits_message_event() -> None:
    app = create_app()
    runtime = app.state.container.runtime
    user_id = UUID(app.state.container.settings.dev_user_id)
    thread_id = None
    run_id = None
    try:
        thread = await runtime.create_thread(
            user_id=user_id,
            title="Agent Worker 测试",
            idempotency_key=f"worker-thread-{uuid4()}",
        )
        thread_id = thread.id
        run = await runtime.create_user_run(
            user_id=user_id,
            thread_id=thread.id,
            content="继续实现 Agent",
            source_ids=[],
            idempotency_key=f"worker-run-{uuid4()}",
        )
        run_id = run.id
        await app.state.container.checkpoints.start()
        worker = build_agent_worker(app.state.container, WorkerGateway())

        status = await worker.run_once(user_id=user_id, run_id=run.id)

        assert status is RunStatus.COMPLETED
        current = await runtime.get_run(user_id=user_id, run_id=run.id)
        messages = await runtime.list_messages(user_id=user_id, thread_id=thread.id)
        events = await runtime.list_events(user_id=user_id, run_id=run.id)
        assert current.status is RunStatus.COMPLETED
        assert messages[-1].content == "已处理：继续实现 Agent"
        assert [event.event for event in events][-2:] == [
            RunEventType.ASSISTANT_COMPLETED,
            RunEventType.RUN_COMPLETED,
        ]
        async with app.state.container.database.engine.connect() as connection:
            checkpoint_ids = set(
                await connection.scalars(
                    text(
                        "SELECT DISTINCT thread_id FROM checkpoints "
                        "WHERE thread_id IN (:run_id, :product_thread_id)"
                    ),
                    {"run_id": str(run.id), "product_thread_id": str(thread.id)},
                )
            )
        assert str(run.id) in checkpoint_ids
        assert str(thread.id) not in checkpoint_ids
    finally:
        if run_id is not None:
            await app.state.container.checkpoints.saver.adelete_thread(str(run_id))
        await app.state.container.checkpoints.stop()
        async with app.state.container.database.engine.begin() as connection:
            if run_id is not None:
                await connection.execute(
                    text("DELETE FROM run_events WHERE run_id = :run_id"), {"run_id": run_id}
                )
                await connection.execute(
                    text("DELETE FROM messages WHERE run_id = :run_id"), {"run_id": run_id}
                )
                await connection.execute(
                    text("DELETE FROM agent_runs WHERE id = :run_id"), {"run_id": run_id}
                )
            if thread_id is not None:
                await connection.execute(
                    text("DELETE FROM threads WHERE id = :thread_id"),
                    {"thread_id": thread_id},
                )
        await app.state.container.database.dispose()


async def test_worker_recovers_terminal_output_without_reinvoking_model() -> None:
    app = create_app()
    runtime = app.state.container.runtime
    user_id = UUID(app.state.container.settings.dev_user_id)
    thread_id = None
    run_id = None
    try:
        thread = await runtime.create_thread(
            user_id=user_id,
            title="Terminal recovery",
            idempotency_key=f"terminal-thread-{uuid4()}",
        )
        thread_id = thread.id
        run = await runtime.create_user_run(
            user_id=user_id,
            thread_id=thread.id,
            content="不要再次调用模型",
            source_ids=[],
            idempotency_key=f"terminal-run-{uuid4()}",
        )
        run_id = run.id
        claimed = await runtime.claim_run(
            user_id=user_id,
            run_id=run.id,
            owner="crashed-worker",
            lease_seconds=60,
        )
        assert claimed is not None and claimed.claim_token is not None
        await runtime.accept_terminal_output(
            user_id=user_id,
            run_id=run.id,
            output={"final_response": "已从持久化终态恢复。"},
            claim_owner="crashed-worker",
            claim_token=claimed.claim_token,
        )
        async with app.state.container.database.engine.begin() as connection:
            await connection.execute(
                text("UPDATE agent_runs SET lease_expires_at = :expired WHERE id = :run_id"),
                {
                    "expired": datetime.now(UTC) - timedelta(seconds=1),
                    "run_id": run.id,
                },
            )

        await app.state.container.checkpoints.start()
        worker = build_agent_worker(app.state.container, NeverCalledGateway())
        assert await worker.run_once(user_id=user_id, run_id=run.id) is RunStatus.COMPLETED
        messages = await runtime.list_messages(user_id=user_id, thread_id=thread.id)
        assert messages[-1].content == "已从持久化终态恢复。"
    finally:
        if run_id is not None:
            await app.state.container.checkpoints.saver.adelete_thread(str(run_id))
        await app.state.container.checkpoints.stop()
        async with app.state.container.database.engine.begin() as connection:
            if run_id is not None:
                for statement in (
                    "DELETE FROM run_events WHERE run_id = :run_id",
                    "DELETE FROM messages WHERE run_id = :run_id",
                    "DELETE FROM agent_runs WHERE id = :run_id",
                ):
                    await connection.execute(text(statement), {"run_id": run_id})
            if thread_id is not None:
                await connection.execute(
                    text("DELETE FROM threads WHERE id = :thread_id"),
                    {"thread_id": thread_id},
                )
        await app.state.container.database.dispose()
