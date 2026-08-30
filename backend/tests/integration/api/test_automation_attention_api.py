import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from laoshiren.infrastructure.automation.run_trigger import RuntimeAutomationRunTrigger
from laoshiren.main import create_app
from laoshiren.workers.automation import run_once
from laoshiren.workers.automation_occurrence import AutomationOccurrenceWorker
from laoshiren.workers.push_delivery import PushDeliveryWorker

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def test_automation_scheduler_outbox_and_attention_feedback() -> None:
    app = create_app()
    headers = {"Authorization": "Bearer change-me"}
    thing_id: UUID | None = None
    automation_ids: list[UUID] = []
    now = datetime.now(UTC)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=headers
        ) as client:
            thing = await client.post(
                "/api/v1/things",
                headers={"Idempotency-Key": f"automation-test-{uuid4()}"},
                json={"name": "自动化测试事务"},
            )
            thing_id = UUID(thing.json()["id"])
            await client.post(
                f"/api/v1/things/{thing_id}/dates",
                headers={"Idempotency-Key": f"automation-test-{uuid4()}"},
                json={
                    "kind": "DEADLINE",
                    "value": (now - timedelta(hours=1)).isoformat(),
                    "timezone": "Asia/Shanghai",
                    "precision": "DATE_TIME",
                    "certainty": "CONFIRMED",
                    "is_primary": True,
                    "expected_version": 1,
                    "reason": "Attention test deadline",
                },
            )

            attention = await client.get("/api/v1/attention")
            deadline_item = next(
                item for item in attention.json()["items"] if item["subject_id"] == str(thing_id)
            )
            assert deadline_item["candidate_type"] == "overdue"
            dismissed_until = now + timedelta(days=1)
            feedback = await client.post(
                f"/api/v1/attention/DEADLINE/{thing_id}/feedback",
                json={
                    "action": "DISMISSED",
                    "dismissed_until": dismissed_until.isoformat(),
                },
            )
            attention_after = await client.get("/api/v1/attention")
            assert feedback.status_code == 204
            assert all(
                item["subject_id"] != str(thing_id) for item in attention_after.json()["items"]
            )

            create_key = f"automation-test-{uuid4()}"
            payload = {
                "automation_type": "ONE_SHOT",
                "title": "提交提醒",
                "message": "请检查提交状态",
                "timezone": "Asia/Shanghai",
                "next_trigger_at": (now - timedelta(minutes=1)).isoformat(),
                "thing_id": str(thing_id),
            }
            created = await client.post(
                "/api/v1/automations",
                headers={"Idempotency-Key": create_key},
                json=payload,
            )
            replay = await client.post(
                "/api/v1/automations",
                headers={"Idempotency-Key": create_key},
                json=payload,
            )
            assert created.status_code == 201
            assert replay.json()["replayed"] is True
            automation_id = UUID(created.json()["id"])
            automation_ids.append(automation_id)

            generated, processed = await run_once(
                app.state.container.automations,
                AutomationOccurrenceWorker(
                    app.state.container.database.automation_unit_of_work,
                    run_trigger=RuntimeAutomationRunTrigger(app.state.container.runtime),
                ),
                PushDeliveryWorker(
                    app.state.container.database.automation_unit_of_work,
                    app.state.container.notification_adapter,
                ),
                limit=10,
            )
            generated_again, _ = await run_once(
                app.state.container.automations,
                AutomationOccurrenceWorker(
                    app.state.container.database.automation_unit_of_work,
                    run_trigger=RuntimeAutomationRunTrigger(app.state.container.runtime),
                ),
                PushDeliveryWorker(
                    app.state.container.database.automation_unit_of_work,
                    app.state.container.notification_adapter,
                ),
                limit=10,
            )
            assert generated == 1
            assert generated_again == 0
            assert processed >= 1

            current = await client.get(f"/api/v1/automations/{automation_id}")
            notifications = await client.get("/api/v1/automations/notifications")
            assert current.json()["status"] == "COMPLETED"
            assert all(
                item["automation_id"] != str(automation_id) for item in notifications.json()
            )

            recurring = await client.post(
                "/api/v1/automations",
                headers={"Idempotency-Key": f"automation-test-{uuid4()}"},
                json={
                    "automation_type": "RECURRING",
                    "title": "周期检查",
                    "message": "检查一次",
                    "timezone": "Asia/Shanghai",
                    "next_trigger_at": (now + timedelta(days=1)).isoformat(),
                    "recurrence_interval_seconds": 3600,
                    "thing_id": str(thing_id),
                },
            )
            recurring_id = UUID(recurring.json()["id"])
            automation_ids.append(recurring_id)
            pause_key = f"automation-test-{uuid4()}"
            paused = await client.patch(
                f"/api/v1/automations/{recurring_id}",
                headers={"Idempotency-Key": pause_key},
                json={"action": "PAUSE", "expected_version": 1},
            )
            replay_pause = await client.patch(
                f"/api/v1/automations/{recurring_id}",
                headers={"Idempotency-Key": pause_key},
                json={"action": "PAUSE", "expected_version": 1},
            )
            assert paused.json()["status"] == "PAUSED"
            assert paused.json()["version"] == 2
            assert replay_pause.json()["replayed"] is True

            condition = await client.post(
                "/api/v1/automations",
                headers={"Idempotency-Key": f"automation-test-{uuid4()}"},
                json={
                    "automation_type": "CONDITION_WATCH",
                    "title": "等待官网结果",
                    "message": "结果发布后通知",
                    "timezone": "Asia/Shanghai",
                    "next_trigger_at": (now + timedelta(days=1)).isoformat(),
                    "thing_id": str(thing_id),
                },
            )
            automation_ids.append(UUID(condition.json()["id"]))
            assert condition.json()["status"] == "PAUSED"
    finally:
        if thing_id is not None:
            async with app.state.container.database.engine.begin() as connection:
                for statement in (
                    "DELETE FROM attention_feedback WHERE user_id = :user_id",
                    "DELETE FROM notification_deliveries WHERE user_id = :user_id",
                    "DELETE FROM notification_intents WHERE automation_id = ANY(:automation_ids)",
                    "DELETE FROM durable_jobs WHERE user_id = :user_id",
                    "DELETE FROM automation_occurrences WHERE automation_id = ANY(:automation_ids)",
                    "DELETE FROM notification_outbox WHERE automation_id = ANY(:automation_ids)",
                    "DELETE FROM automation_operations WHERE automation_id = ANY(:automation_ids)",
                    "DELETE FROM automations WHERE id = ANY(:automation_ids)",
                    "DELETE FROM timeline_events WHERE thing_id = :thing_id",
                    "DELETE FROM state_mutations WHERE thing_id = :thing_id",
                    "DELETE FROM thing_dates WHERE thing_id = :thing_id",
                    "DELETE FROM things WHERE id = :thing_id",
                ):
                    await connection.execute(
                        text(statement),
                        {
                            "user_id": UUID(app.state.container.settings.dev_user_id),
                            "thing_id": thing_id,
                            "automation_ids": automation_ids,
                        },
                    )
        await app.state.container.database.dispose()
