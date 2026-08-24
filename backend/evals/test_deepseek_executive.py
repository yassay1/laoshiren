import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from laoshiren.bootstrap import build_configured_agent_worker
from laoshiren.domain.runtime.entities import RunStatus
from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("RUN_MODEL_EVALS") != "1",
        reason="Set RUN_MODEL_EVALS=1 to spend model quota on live evals.",
    ),
]


async def test_live_executive_completes_a_simple_run() -> None:
    app = create_app()
    container = app.state.container
    user_id = UUID(container.settings.dev_user_id)
    thread_id = None
    run_id = None
    checkpoints_started = False
    try:
        thread = await container.runtime.create_thread(
            user_id=user_id,
            title="DeepSeek Executive Eval",
            idempotency_key=f"eval-thread-{uuid4()}",
        )
        thread_id = thread.id
        run = await container.runtime.create_user_run(
            user_id=user_id,
            thread_id=thread.id,
            content="你好，请用一句简短中文介绍你能为我做什么。",
            source_ids=[],
            idempotency_key=f"eval-run-{uuid4()}",
        )
        run_id = run.id
        await container.checkpoints.start()
        checkpoints_started = True
        worker = build_configured_agent_worker(container)

        status = await worker.run_once(user_id=user_id, run_id=run.id)

        messages = await container.runtime.list_messages(
            user_id=user_id, thread_id=thread.id
        )
        assert status is RunStatus.COMPLETED
        assert messages[-1].content.strip()
        assert messages[-1].role.value == "ASSISTANT"
    finally:
        if checkpoints_started and thread_id is not None:
            await container.checkpoints.saver.adelete_thread(str(thread_id))
        await container.checkpoints.stop()
        async with container.database.engine.begin() as connection:
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
        await container.database.dispose()
