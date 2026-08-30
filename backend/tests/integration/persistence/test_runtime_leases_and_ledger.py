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
    thing_id = None
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
            owner="shared-worker",
            lease_seconds=60,
        )
        assert first is not None
        assert first.status is RunStatus.RUNNING
        assert first.attempt_count == 1
        assert (
            await runtime.claim_run(
                user_id=user_id,
                run_id=run_id,
                owner="shared-worker",
                lease_seconds=60,
            )
            is None
        )

        async with container.database.engine.begin() as connection:
            await connection.execute(
                text("UPDATE agent_runs SET lease_expires_at = :expired WHERE id = :run_id"),
                {
                    "expired": datetime.now(UTC) - timedelta(seconds=1),
                    "run_id": run_id,
                },
            )
        takeover = await runtime.claim_run(
            user_id=user_id,
            run_id=run_id,
            owner="shared-worker",
            lease_seconds=60,
        )
        assert takeover is not None
        assert first.claim_token is not None
        assert takeover.claim_token is not None
        assert takeover.claim_token != first.claim_token
        assert takeover.attempt_count == 2
        assert (
            await runtime.renew_run_lease(
                user_id=user_id,
                run_id=run_id,
                owner="shared-worker",
                claim_token=first.claim_token,
                lease_seconds=60,
            )
            is False
        )
        with pytest.raises(InvalidStateTransition, match="no longer owned"):
            await runtime.complete_run(
                user_id=user_id,
                run_id=run_id,
                content="stale result",
                claim_owner="shared-worker",
                claim_token=first.claim_token,
            )

        thing = await container.personal_state.create_thing(
            user_id=user_id,
            name="Atomic archive receipt",
            action_id=f"create-{uuid4()}",
            idempotency_key=f"create-{uuid4()}",
            reason="integration setup",
        )
        thing_id = thing.id
        atomic_action_id = "atomic-archive"
        atomic_claim = await runtime.claim_tool_execution(
            user_id=user_id,
            run_id=run_id,
            action_id=atomic_action_id,
            tool_name="thing_change_state",
            arguments_hash="e" * 64,
            owner="shared-worker",
            run_claim_token=takeover.claim_token,
            lease_seconds=60,
        )
        assert atomic_claim.claim_token is not None
        atomic_result = await runtime.archive_thing_and_complete_tool_execution(
            user_id=user_id,
            run_id=run_id,
            action_id=atomic_action_id,
            owner="shared-worker",
            claim_token=atomic_claim.claim_token,
            thing_id=thing.id,
            expected_version=thing.version,
            idempotency_key=f"agent:{run_id}:{atomic_action_id}",
            reason="archive atomically",
        )
        archived = await container.personal_state.get_thing(user_id=user_id, thing_id=thing.id)
        assert archived.version == atomic_result["version"]
        async with container.database.engine.connect() as connection:
            receipt = await connection.scalar(
                text(
                    "SELECT receipt FROM tool_executions "
                    "WHERE run_id = :run_id AND action_id = :action_id"
                ),
                {"run_id": run_id, "action_id": atomic_action_id},
            )
        assert receipt["data"] == atomic_result

        action_id = "action-one"
        claim = await runtime.claim_tool_execution(
            user_id=user_id,
            run_id=run_id,
            action_id=action_id,
            tool_name="thing_create",
            arguments_hash="a" * 64,
            owner="shared-worker",
            run_claim_token=takeover.claim_token,
            lease_seconds=60,
        )
        assert claim.acquired is True
        assert claim.claim_token is not None
        busy = await runtime.claim_tool_execution(
            user_id=user_id,
            run_id=run_id,
            action_id=action_id,
            tool_name="thing_create",
            arguments_hash="a" * 64,
            owner="shared-worker",
            run_claim_token=takeover.claim_token,
            lease_seconds=60,
        )
        assert busy.acquired is False
        assert busy.cached_result is None
        result = {"status": "SUCCESS", "code": "THING_CREATED", "data": {"id": "1"}}
        await runtime.complete_tool_execution(
            user_id=user_id,
            run_id=run_id,
            action_id=action_id,
            owner="shared-worker",
            claim_token=claim.claim_token,
            result=result,
            succeeded=True,
        )
        replay = await runtime.claim_tool_execution(
            user_id=user_id,
            run_id=run_id,
            action_id=action_id,
            tool_name="thing_create",
            arguments_hash="a" * 64,
            owner="shared-worker",
            run_claim_token=takeover.claim_token,
            lease_seconds=60,
        )
        assert replay.cached_result == result
        async with container.database.engine.connect() as connection:
            persisted_receipt = await connection.scalar(
                text(
                    "SELECT receipt FROM tool_executions "
                    "WHERE run_id = :run_id AND action_id = :action_id"
                ),
                {"run_id": run_id, "action_id": action_id},
            )
        assert persisted_receipt == result

        failed_action_id = "deterministic-failure"
        failed_claim = await runtime.claim_tool_execution(
            user_id=user_id,
            run_id=run_id,
            action_id=failed_action_id,
            tool_name="thing_change_state",
            arguments_hash="c" * 64,
            owner="shared-worker",
            run_claim_token=takeover.claim_token,
            lease_seconds=60,
        )
        assert failed_claim.claim_token is not None
        failed_result = {
            "status": "FAILED",
            "code": "VERSION_CONFLICT",
            "error": {"code": "VERSION_CONFLICT", "retryable": False},
        }
        await runtime.complete_tool_execution(
            user_id=user_id,
            run_id=run_id,
            action_id=failed_action_id,
            owner="shared-worker",
            claim_token=failed_claim.claim_token,
            result=failed_result,
            succeeded=False,
        )
        failed_replay = await runtime.claim_tool_execution(
            user_id=user_id,
            run_id=run_id,
            action_id=failed_action_id,
            tool_name="thing_change_state",
            arguments_hash="c" * 64,
            owner="shared-worker",
            run_claim_token=takeover.claim_token,
            lease_seconds=60,
        )
        assert failed_replay.cached_result == failed_result

        in_flight_action_id = "replayable-state-mutation"
        in_flight_claim = await runtime.claim_tool_execution(
            user_id=user_id,
            run_id=run_id,
            action_id=in_flight_action_id,
            tool_name="thing_change_state",
            arguments_hash="d" * 64,
            owner="shared-worker",
            run_claim_token=takeover.claim_token,
            lease_seconds=60,
        )
        assert in_flight_claim.acquired is True
        current = await runtime.get_run(user_id=user_id, run_id=run_id)
        with pytest.raises(InvalidStateTransition, match="Tool execution is in flight"):
            await runtime.cancel_run(
                user_id=user_id,
                run_id=run_id,
                expected_version=current.version,
                idempotency_key=f"cancel-during-tool-{uuid4()}",
            )
        assert in_flight_claim.claim_token is not None
        await runtime.complete_tool_execution(
            user_id=user_id,
            run_id=run_id,
            action_id=in_flight_action_id,
            owner="shared-worker",
            claim_token=in_flight_claim.claim_token,
            result={"status": "SUCCESS", "code": "THING_UPDATED"},
            succeeded=True,
        )

        unsafe_action_id = "external-non-replayable"
        unsafe_claim = await runtime.claim_tool_execution(
            user_id=user_id,
            run_id=run_id,
            action_id=unsafe_action_id,
            tool_name="external.charge",
            arguments_hash="b" * 64,
            owner="shared-worker",
            run_claim_token=takeover.claim_token,
            lease_seconds=60,
            replay_safe=False,
            idempotency_key=f"agent:{run_id}:{unsafe_action_id}",
        )
        assert unsafe_claim.acquired is True
        async with container.database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE tool_executions SET lease_expires_at = :expired "
                    "WHERE run_id = :run_id AND action_id = :action_id"
                ),
                {
                    "expired": datetime.now(UTC) - timedelta(seconds=1),
                    "run_id": run_id,
                    "action_id": unsafe_action_id,
                },
            )
        blocked = await runtime.claim_tool_execution(
            user_id=user_id,
            run_id=run_id,
            action_id=unsafe_action_id,
            tool_name="external.charge",
            arguments_hash="b" * 64,
            owner="shared-worker",
            run_claim_token=takeover.claim_token,
            lease_seconds=60,
            replay_safe=False,
            idempotency_key=f"agent:{run_id}:{unsafe_action_id}",
        )
        assert blocked.acquired is False
        assert blocked.cached_result is None
        assert blocked.blocked_reason is not None
        assert "outcome is unknown" in blocked.blocked_reason
        async with container.database.engine.connect() as connection:
            unknown_row = (
                await connection.execute(
                    text(
                        "SELECT status::text, error_code FROM tool_executions "
                        "WHERE run_id = :run_id AND action_id = :action_id"
                    ),
                    {"run_id": run_id, "action_id": unsafe_action_id},
                )
            ).one()
        assert unknown_row == ("UNKNOWN_OUTCOME", "UNKNOWN_OUTCOME")

        await runtime.fail_run(
            user_id=user_id,
            run_id=run_id,
            error_code="TEST_FINISHED",
            claim_owner="shared-worker",
            claim_token=takeover.claim_token,
        )
    finally:
        async with container.database.engine.begin() as connection:
            if thing_id is not None:
                await connection.execute(
                    text("DELETE FROM timeline_events WHERE thing_id = :thing_id"),
                    {"thing_id": thing_id},
                )
                await connection.execute(
                    text("DELETE FROM state_mutations WHERE thing_id = :thing_id"),
                    {"thing_id": thing_id},
                )
                await connection.execute(
                    text("DELETE FROM things WHERE id = :thing_id"),
                    {"thing_id": thing_id},
                )
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
