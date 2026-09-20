import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

import laoshiren.application.automations.occurrence_execution as occurrence_module
from laoshiren.application.automations.occurrence_execution import (
    AutomationOccurrenceApplicationService,
    OccurrenceExecutionResult,
)
from laoshiren.application.runtime.durable_job_claim import claim_ready_jobs
from laoshiren.domain.automations.entities import AutomationType
from laoshiren.domain.runtime.entities import DurableJobKind
from laoshiren.main import create_app
from laoshiren.workers.automation_occurrence import AutomationOccurrenceWorker

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.gate_c,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def prepare_due_occurrence(container) -> tuple[UUID, UUID, UUID]:
    now = datetime.now(UTC)
    user_id = uuid4()
    automation = await container.automations.create(
        user_id=user_id,
        automation_type=AutomationType.ONCE,
        title="Recovery reminder",
        message="Check the result",
        timezone_name="Asia/Shanghai",
        next_trigger_at=now - timedelta(minutes=1),
        idempotency_key=f"occurrence-recovery-{uuid4()}",
    )
    assert await container.automations.process_due(now=now) >= 1
    async with container.database.engine.connect() as connection:
        job_id = await connection.scalar(
            text(
                "SELECT id FROM durable_jobs WHERE kind = 'AUTOMATION_OCCURRENCE' "
                "AND payload->>'automation_id' = :automation_id"
            ),
            {"automation_id": str(automation.id)},
        )
    assert isinstance(job_id, UUID)
    async with container.database.engine.connect() as connection:
        automation_row = await connection.execute(
            text("SELECT status, next_trigger_at FROM automations WHERE id = :automation_id"),
            {"automation_id": automation.id},
        )
    assert automation_row.one() == ("ACTIVE", None)
    async with container.database.automation_unit_of_work() as uow:
        due_again = await uow.automations.list_due(now=now, limit=100)
        assert all(item.id != automation.id for item in due_again)
        await uow.rollback()
    async with container.database.engine.connect() as connection:
        occurrence_count = await connection.scalar(
            text(
                "SELECT count(*) FROM automation_occurrences "
                "WHERE automation_id = :automation_id"
            ),
            {"automation_id": automation.id},
        )
    assert occurrence_count == 1
    return user_id, automation.id, job_id


async def cleanup(container, *, user_id: UUID, automation_id: UUID) -> None:
    values = {
        "user_id": user_id,
        "automation_id": automation_id,
        "automation_id_text": str(automation_id),
    }
    async with container.database.engine.begin() as connection:
        await connection.execute(
            text(
                "DELETE FROM durable_jobs WHERE user_id = :user_id "
                "AND (payload->>'automation_id' = :automation_id_text "
                "OR payload->>'intent_id' IN "
                "(SELECT CAST(id AS text) FROM notification_intents "
                "WHERE automation_id = :automation_id))"
            ),
            values,
        )
        await connection.execute(
            text(
                "DELETE FROM notification_deliveries WHERE intent_id IN "
                "(SELECT id FROM notification_intents WHERE automation_id = :automation_id)"
            ),
            values,
        )
        await connection.execute(
            text("DELETE FROM notification_intents WHERE automation_id = :automation_id"),
            values,
        )
        await connection.execute(
            text("DELETE FROM automation_occurrences WHERE automation_id = :automation_id"),
            values,
        )
        await connection.execute(
            text("DELETE FROM automations WHERE id = :automation_id"), values
        )
        await connection.execute(text("DELETE FROM users WHERE id = :user_id"), values)


async def test_automation_trigger_column_accepts_null_after_migration() -> None:
    app = create_app()
    container = app.state.container
    try:
        async with container.database.engine.connect() as connection:
            nullable = await connection.scalar(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_schema = current_schema() "
                    "AND table_name = 'automations' AND column_name = 'next_trigger_at'"
                )
            )
        assert nullable == "YES"
    finally:
        await container.database.dispose()


async def test_notification_write_failure_retries_without_losing_reminder(monkeypatch) -> None:
    app = create_app()
    container = app.state.container
    user_id, automation_id, job_id = await prepare_due_occurrence(container)
    original = occurrence_module.create_reminder_notification
    service = AutomationOccurrenceApplicationService(
        container.database.automation_unit_of_work,
        retry_base_seconds=0.01,
    )
    worker = AutomationOccurrenceWorker(container.database.automation_unit_of_work, service)

    async def fail_once(*args, **kwargs):
        raise RuntimeError("injected notification write failure")

    try:
        monkeypatch.setattr(occurrence_module, "create_reminder_notification", fail_once)
        assert await worker.run_once()
        async with container.database.engine.connect() as connection:
            job_status = await connection.scalar(
                text("SELECT status FROM durable_jobs WHERE id = :job_id"), {"job_id": job_id}
            )
            occurrence_status = await connection.scalar(
                text(
                    "SELECT status FROM automation_occurrences "
                    "WHERE automation_id = :automation_id"
                ),
                {"automation_id": automation_id},
            )
            intent_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM notification_intents "
                    "WHERE automation_id = :automation_id"
                ),
                {"automation_id": automation_id},
            )
            automation_status = await connection.scalar(
                text("SELECT status FROM automations WHERE id = :automation_id"),
                {"automation_id": automation_id},
            )
        assert job_status == "READY"
        assert occurrence_status == "MATERIALIZED"
        assert intent_count == 0
        assert automation_status == "ACTIVE"

        monkeypatch.setattr(occurrence_module, "create_reminder_notification", original)
        await asyncio.sleep(0.02)
        assert await worker.run_once()
        async with container.database.engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT j.status, o.status, a.status, "
                        "(SELECT count(*) FROM notification_intents i "
                        "WHERE i.automation_id = :automation_id) "
                        "FROM durable_jobs j JOIN automation_occurrences o "
                        "ON o.durable_job_id = j.id "
                        "JOIN automations a ON a.id = o.automation_id "
                        "WHERE j.id = :job_id"
                    ),
                    {"job_id": job_id, "automation_id": automation_id},
                )
            ).one()
        assert row == ("COMPLETED", "SUCCEEDED", "COMPLETED", 1)
    finally:
        await cleanup(container, user_id=user_id, automation_id=automation_id)
        await container.database.dispose()


async def test_lost_claim_rolls_back_notification_reaction(monkeypatch) -> None:
    app = create_app()
    container = app.state.container
    user_id, automation_id, job_id = await prepare_due_occurrence(container)
    original = occurrence_module.create_reminder_notification
    service = AutomationOccurrenceApplicationService(container.database.automation_unit_of_work)
    now = datetime.now(UTC)
    try:
        async with container.database.automation_unit_of_work() as uow:
            jobs = await claim_ready_jobs(
                uow,
                kind=DurableJobKind.AUTOMATION_OCCURRENCE,
                owner="original-worker",
                now=now,
                lease_until=now + timedelta(minutes=2),
                limit=1,
            )
            await uow.commit()
        assert len(jobs) == 1 and jobs[0].id == job_id

        async def steal_claim(uow, **kwargs):
            async with container.database.engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE durable_jobs SET claim_epoch = claim_epoch + 1, "
                        "claimed_by = 'replacement-worker' WHERE id = :job_id"
                    ),
                    {"job_id": job_id},
                )
            return await original(uow, **kwargs)

        monkeypatch.setattr(occurrence_module, "create_reminder_notification", steal_claim)
        result = await service.execute_claimed(job=jobs[0], owner="original-worker")
        assert result is OccurrenceExecutionResult.LOST_CLAIM
        async with container.database.engine.connect() as connection:
            intent_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM notification_intents "
                    "WHERE automation_id = :automation_id"
                ),
                {"automation_id": automation_id},
            )
            occurrence_status = await connection.scalar(
                text(
                    "SELECT status FROM automation_occurrences "
                    "WHERE automation_id = :automation_id"
                ),
                {"automation_id": automation_id},
            )
            automation_status = await connection.scalar(
                text("SELECT status FROM automations WHERE id = :automation_id"),
                {"automation_id": automation_id},
            )
        assert intent_count == 0
        assert occurrence_status == "MATERIALIZED"
        assert automation_status == "ACTIVE"
    finally:
        await cleanup(container, user_id=user_id, automation_id=automation_id)
        await container.database.dispose()


async def test_expired_final_attempt_sets_job_and_occurrence_failed() -> None:
    app = create_app()
    container = app.state.container
    user_id, automation_id, job_id = await prepare_due_occurrence(container)
    service = AutomationOccurrenceApplicationService(container.database.automation_unit_of_work)
    worker = AutomationOccurrenceWorker(container.database.automation_unit_of_work, service)
    try:
        async with container.database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE durable_jobs SET status = 'CLAIMED', "
                    "claimed_by = 'expired-worker', claim_epoch = 5, "
                    "delivery_attempt = max_delivery_attempts, lease_until = :expired "
                    "WHERE id = :job_id"
                ),
                {"job_id": job_id, "expired": datetime.now(UTC) - timedelta(seconds=1)},
            )

        assert await worker.run_once() is False
        async with container.database.engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT j.status, j.last_error_code, o.status, a.status "
                        "FROM durable_jobs j JOIN automation_occurrences o "
                        "ON o.durable_job_id = j.id "
                        "JOIN automations a ON a.id = o.automation_id "
                        "WHERE j.id = :job_id"
                    ),
                    {"job_id": job_id},
                )
            ).one()
        assert row == ("FAILED", "RECOVERY_EXHAUSTED", "FAILED", "COMPLETED")
    finally:
        await cleanup(container, user_id=user_id, automation_id=automation_id)
        await container.database.dispose()
