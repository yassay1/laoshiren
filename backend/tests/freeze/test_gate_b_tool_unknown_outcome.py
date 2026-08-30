import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.gate_b,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def test_unknown_outcome_blocks_blind_external_tool_replay() -> None:
    app = create_app()
    container = app.state.container
    runtime = container.runtime
    user_id = UUID(container.settings.dev_user_id)
    thread_id = None
    run_id = None

    try:
        thread = await runtime.create_thread(
            user_id=user_id,
            title="Gate B unknown outcome",
            idempotency_key=f"gate-b-unknown-{uuid4()}",
        )
        thread_id = thread.id
        run = await runtime.create_user_run(
            user_id=user_id,
            thread_id=thread_id,
            content="charge card",
            source_ids=[],
            idempotency_key=f"gate-b-unknown-run-{uuid4()}",
        )
        run_id = run.id
        claimed = await runtime.claim_run(
            user_id=user_id,
            run_id=run_id,
            owner="gate-b-worker",
            lease_seconds=60,
        )
        assert claimed is not None
        assert claimed.claim_token is not None

        action_id = "external-non-replayable"
        first = await runtime.claim_tool_execution(
            user_id=user_id,
            run_id=run_id,
            action_id=action_id,
            tool_name="external.charge",
            arguments_hash="b" * 64,
            owner="gate-b-worker",
            run_claim_token=claimed.claim_token,
            lease_seconds=60,
            replay_safe=False,
            idempotency_key=f"agent:{run_id}:{action_id}",
        )
        assert first.acquired is True

        async with container.database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE tool_executions SET lease_expires_at = :expired "
                    "WHERE run_id = :run_id AND action_id = :action_id"
                ),
                {
                    "expired": datetime.now(UTC) - timedelta(seconds=1),
                    "run_id": run_id,
                    "action_id": action_id,
                },
            )

        blocked = await runtime.claim_tool_execution(
            user_id=user_id,
            run_id=run_id,
            action_id=action_id,
            tool_name="external.charge",
            arguments_hash="b" * 64,
            owner="gate-b-worker",
            run_claim_token=claimed.claim_token,
            lease_seconds=60,
            replay_safe=False,
            idempotency_key=f"agent:{run_id}:{action_id}",
        )
        assert blocked.acquired is False
        assert blocked.cached_result is None
        assert blocked.blocked_reason is not None
        assert "outcome is unknown" in blocked.blocked_reason.lower()

        async with container.database.engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT status::text, error_code FROM tool_executions "
                        "WHERE run_id = :run_id AND action_id = :action_id"
                    ),
                    {"run_id": run_id, "action_id": action_id},
                )
            ).one()
        assert row == ("UNKNOWN_OUTCOME", "UNKNOWN_OUTCOME")

        await runtime.fail_run(
            user_id=user_id,
            run_id=run_id,
            error_code="GATE_B_DONE",
            claim_owner="gate-b-worker",
            claim_token=claimed.claim_token,
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
