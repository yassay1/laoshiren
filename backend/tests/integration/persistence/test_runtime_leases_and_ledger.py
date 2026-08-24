import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from laoshiren.domain.personal_state.exceptions import InvalidStateTransition
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


async def test_concurrent_idempotency_run_lease_and_tool_ledger() -> None:
    app = create_app()
    container = app.state.container
    runtime = container.runtime
    user_id = UUID(container.settings.dev_user_id)
    thread_id = None
    run_id = None
    try:
        thread_key = f"concurrent-thread-{uuid4()}"
        threads = await asyncio.gather(
            *(
                runtime.create_thread(
                    user_id=user_id,
                    title="Concurrent thread",
                    idempotency_key=thread_key,
                )
                for _ in range(5)
            )
        )
        assert len({item.id for item in threads}) == 1
        assert sum(item.replayed for item in threads) == 4
        thread_id = threads[0].id

        run_key = f"concurrent-run-{uuid4()}"
        runs = await asyncio.gather(
            *(
                runtime.create_user_run(
                    user_id=user_id,
                    thread_id=thread_id,
                    content="execute exactly once",
                    source_ids=[],
                    idempotency_key=run_key,
                )
                for _ in range(5)
            )
        )
        assert len({item.id for item in runs}) == 1
        assert sum(item.replayed for item in runs) == 4
        run_id = runs[0].id
        messages = await runtime.list_messages(user_id=user_id, thread_id=thread_id)
        assert len(messages) == 1

        first = await runtime.claim_run(
            user_id=user_id,
            run_id=run_id,
            owner="worker-one",
            lease_seconds=60,
        )
        assert first is not None
        assert first.status is RunStatus.RUNNING
        assert first.attempt_count == 1
        assert await runtime.claim_run(
            user_id=user_id,
            run_id=run_id,
            owner="worker-two",
            lease_seconds=60,
        ) is None

        async with container.database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE agent_runs SET lease_expires_at = :expired "
                    "WHERE id = :run_id"
                ),
                {
                    "expired": datetime.now(UTC) - timedelta(seconds=1),
                    "run_id": run_id,
                },
            )
        takeover = await runtime.claim_run(
            user_id=user_id,
            run_id=run_id,
            owner="worker-two",
            lease_seconds=60,
        )
        assert takeover is not None
        assert takeover.attempt_count == 2
        assert await runtime.renew_run_lease(
            user_id=user_id,
            run_id=run_id,
            owner="worker-one",
            lease_seconds=60,
        ) is False
        with pytest.raises(InvalidStateTransition, match="no longer owned"):
            await runtime.complete_run(
                user_id=user_id,
                run_id=run_id,
                content="stale result",
                claim_owner="worker-one",
            )

        action_id = "action-one"
        claim = await runtime.claim_tool_execution(
            user_id=user_id,
            run_id=run_id,
            action_id=action_id,
            tool_name="state.create_thing",
            arguments_hash="a" * 64,
            owner="worker-two",
            lease_seconds=60,
        )
        assert claim.acquired is True
        busy = await runtime.claim_tool_execution(
            user_id=user_id,
            run_id=run_id,
            action_id=action_id,
            tool_name="state.create_thing",
            arguments_hash="a" * 64,
            owner="worker-two",
            lease_seconds=60,
        )
        assert busy.acquired is False
        assert busy.cached_result is None
        result = {"status": "SUCCESS", "code": "THING_CREATED", "data": {"id": "1"}}
        await runtime.complete_tool_execution(
            user_id=user_id,
            run_id=run_id,
            action_id=action_id,
            owner="worker-two",
            result=result,
            succeeded=True,
        )
        replay = await runtime.claim_tool_execution(
            user_id=user_id,
            run_id=run_id,
            action_id=action_id,
            tool_name="state.create_thing",
            arguments_hash="a" * 64,
            owner="worker-two",
            lease_seconds=60,
        )
        assert replay.cached_result == result

        await runtime.fail_run(
            user_id=user_id,
            run_id=run_id,
            error_code="TEST_FINISHED",
            claim_owner="worker-two",
        )
    finally:
        async with container.database.engine.begin() as connection:
            if run_id is not None:
                for statement in (
                    "DELETE FROM tool_executions WHERE run_id = :run_id",
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
        await container.database.dispose()
