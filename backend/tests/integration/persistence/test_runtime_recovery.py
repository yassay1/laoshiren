import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from laoshiren.domain.runtime.entities import RunStatus
from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def test_running_run_is_requeued_after_service_restart_recovery() -> None:
    app = create_app()
    runtime = app.state.container.runtime
    user_id = UUID(app.state.container.settings.dev_user_id)
    thread_id = None
    run_id = None
    try:
        thread = await runtime.create_thread(
            user_id=user_id,
            title="Recovery test",
            idempotency_key=f"recovery-thread-{uuid4()}",
        )
        thread_id = thread.id
        run = await runtime.create_user_run(
            user_id=user_id,
            thread_id=thread.id,
            content="recover me",
            source_ids=[],
            idempotency_key=f"recovery-run-{uuid4()}",
        )
        run_id = run.id
        await runtime.start_run(
            user_id=user_id, run_id=run.id, phase="tool", label="in flight"
        )

        recovered = await runtime.recover_pending_runs()
        current = await runtime.get_run(user_id=user_id, run_id=run.id)
        events = await runtime.list_events(user_id=user_id, run_id=run.id)

        assert recovered >= 1
        assert current.status is RunStatus.QUEUED
        assert events[-1].data["reason"] == "service_restart"
    finally:
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
