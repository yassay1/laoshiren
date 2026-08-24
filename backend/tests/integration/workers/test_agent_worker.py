import os
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
        self, *, state: GraphState, available_tools: tuple[str, ...]
    ) -> ExecutiveDecision:
        assert "state.get_thing" in available_tools
        assert "state.set_deadline" in available_tools
        return ExecutiveDecision(
            DecisionKind.RESPOND,
            content=f"已处理：{state['current_input']}",
        )


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
            RunEventType.ASSISTANT_MESSAGE,
            RunEventType.RUN_COMPLETED,
        ]
    finally:
        if thread_id is not None:
            await app.state.container.checkpoints.saver.adelete_thread(str(thread_id))
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
