import os
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def test_personal_state_product_api_flow() -> None:
    app = create_app()
    headers = {"Authorization": "Bearer change-me"}
    thing_id: UUID | None = None

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=headers,
        ) as client:
            thing_key = f"api-test-{uuid4()}"
            create_thing = await client.post(
                "/api/v1/things",
                headers={"Idempotency-Key": thing_key},
                json={"name": "API 集成测试"},
            )
            replay_thing = await client.post(
                "/api/v1/things",
                headers={"Idempotency-Key": thing_key},
                json={"name": "API 集成测试"},
            )

            assert create_thing.status_code == 201
            assert replay_thing.status_code == 201
            assert replay_thing.json()["id"] == create_thing.json()["id"]
            thing_id = UUID(create_thing.json()["id"])

            deadline_key = f"api-test-{uuid4()}"
            deadline_payload = {
                "kind": "DEADLINE",
                "value": "2026-09-01T18:00:00+08:00",
                "timezone": "Asia/Shanghai",
                "precision": "DATETIME",
                "certainty": "CONFIRMED",
                "is_primary": True,
                "expected_version": 1,
                "reason": "API integration test",
            }
            set_deadline = await client.post(
                f"/api/v1/things/{thing_id}/dates",
                headers={"Idempotency-Key": deadline_key},
                json=deadline_payload,
            )
            replay_deadline = await client.post(
                f"/api/v1/things/{thing_id}/dates",
                headers={"Idempotency-Key": deadline_key},
                json=deadline_payload,
            )
            thing = await client.get(f"/api/v1/things/{thing_id}")

            assert set_deadline.status_code == 200
            assert set_deadline.json()["target_version"] == 2
            assert set_deadline.json()["replayed"] is False
            assert replay_deadline.status_code == 200
            assert replay_deadline.json()["replayed"] is True
            assert thing.status_code == 200
            assert thing.json()["deadline_at"] == "2026-09-01T10:00:00Z"
            assert thing.json()["version"] == 2

            update_key = f"api-test-{uuid4()}"
            update_thing = await client.patch(
                f"/api/v1/things/{thing_id}",
                headers={"Idempotency-Key": update_key},
                json={
                    "name": "API 集成测试（更新）",
                    "status": "ACTIVE",
                    "current_stage": "执行中",
                    "expected_version": 2,
                    "reason": "API integration test",
                },
            )
            dates = await client.get(f"/api/v1/things/{thing_id}/dates")

            assert update_thing.status_code == 200
            assert update_thing.json()["name"] == "API 集成测试（更新）"
            assert update_thing.json()["status"] == "ACTIVE"
            assert update_thing.json()["current_stage"] == "执行中"
            assert update_thing.json()["version"] == 3
            assert dates.status_code == 200
            assert len(dates.json()) == 1
            assert dates.json()[0]["certainty"] == "CONFIRMED"
            assert dates.json()[0]["is_primary"] is True

            create_task = await client.post(
                f"/api/v1/things/{thing_id}/tasks",
                headers={"Idempotency-Key": f"api-test-{uuid4()}"},
                json={"title": "完成 Product API"},
            )
            assert create_task.status_code == 201
            task = create_task.json()

            complete_key = f"api-test-{uuid4()}"
            complete = await client.patch(
                f"/api/v1/tasks/{task['id']}",
                headers={"Idempotency-Key": complete_key},
                json={
                    "status": "DONE",
                    "expected_version": task["version"],
                    "reason": "API integration test",
                },
            )
            replay_complete = await client.patch(
                f"/api/v1/tasks/{task['id']}",
                headers={"Idempotency-Key": complete_key},
                json={
                    "status": "DONE",
                    "expected_version": task["version"],
                    "reason": "API integration test replay",
                },
            )
            conflict = await client.patch(
                f"/api/v1/tasks/{task['id']}",
                headers={"Idempotency-Key": f"api-test-{uuid4()}"},
                json={
                    "status": "DONE",
                    "expected_version": task["version"],
                    "reason": "stale API integration test",
                },
            )
            tasks = await client.get(f"/api/v1/things/{thing_id}/tasks")

            assert complete.status_code == 200
            assert complete.json()["replayed"] is False
            assert replay_complete.status_code == 200
            assert replay_complete.json()["replayed"] is True
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "VERSION_CONFLICT"
            assert conflict.json()["error"]["request_id"] == conflict.headers["X-Request-ID"]
            assert tasks.status_code == 200
            assert tasks.json()[0]["status"] == "DONE"
            assert tasks.json()[0]["version"] == 2

            timeline = await client.get(f"/api/v1/things/{thing_id}/timeline")
            completed_timeline = await client.get(
                f"/api/v1/things/{thing_id}/timeline",
                params={"event_type": "TASK_COMPLETED"},
            )
            assert timeline.status_code == 200
            assert len(timeline.json()) == 5
            assert timeline.json()[0]["event_type"] == "TASK_COMPLETED"
            assert completed_timeline.status_code == 200
            assert len(completed_timeline.json()) == 1
    finally:
        if thing_id is not None:
            database = app.state.container.database
            async with database.engine.begin() as connection:
                statements = [
                    "DELETE FROM timeline_events WHERE thing_id = :thing_id",
                    "DELETE FROM state_mutations WHERE thing_id = :thing_id",
                    "DELETE FROM tasks WHERE thing_id = :thing_id",
                    "DELETE FROM thing_dates WHERE thing_id = :thing_id",
                    "DELETE FROM things WHERE id = :thing_id",
                ]
                for statement in statements:
                    await connection.execute(text(statement), {"thing_id": thing_id})
        await app.state.container.database.dispose()


async def test_product_api_error_contract() -> None:
    app = create_app()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            unauthorized = await client.get(
                "/api/v1/things", headers={"X-Request-ID": "contract-test"}
            )
            invalid = await client.post(
                "/api/v1/things",
                headers={
                    "Authorization": "Bearer change-me",
                    "Idempotency-Key": "contract-test-invalid",
                },
                json={"name": ""},
            )

            assert unauthorized.status_code == 401
            assert unauthorized.json()["error"] == {
                "code": "HTTP_ERROR",
                "message": "Invalid or missing bearer token.",
                "request_id": "contract-test",
            }
            assert invalid.status_code == 422
            assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
            assert invalid.json()["error"]["request_id"] == invalid.headers["X-Request-ID"]
            assert invalid.json()["error"]["details"]
    finally:
        await app.state.container.database.dispose()
