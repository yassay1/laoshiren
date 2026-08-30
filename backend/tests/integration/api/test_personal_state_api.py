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
                "precision": "DATE_TIME",
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
            assert dates.json()[0]["kind"] == "DEADLINE"
            assert dates.json()[0]["label"] is None
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


async def test_standalone_recurring_task_advances_without_automation() -> None:
    app = create_app()
    headers = {"Authorization": "Bearer change-me"}
    task_id: UUID | None = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=headers
        ) as client:
            created = await client.post(
                "/api/v1/tasks",
                headers={"Idempotency-Key": f"recurring-{uuid4()}"},
                json={
                    "title": "Weekly review",
                    "due_at": "2026-09-06T09:00:00+00:00",
                    "recurrence_interval_days": 7,
                },
            )
            assert created.status_code == 201
            task_id = UUID(created.json()["id"])
            assert created.json()["thing_id"] is None
            advanced = await client.patch(
                f"/api/v1/tasks/{task_id}",
                headers={"Idempotency-Key": f"advance-{uuid4()}"},
                json={"status": "DONE", "expected_version": 1, "reason": "completed"},
            )
            assert advanced.status_code == 200
            tasks = await client.get("/api/v1/tasks")
            assert tasks.status_code == 200
            assert tasks.json()[0]["status"] == "TODO"
            assert tasks.json()[0]["due_at"] == "2026-09-13T09:00:00Z"
    finally:
        if task_id is not None:
            database = app.state.container.database
            async with database.engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM state_mutations WHERE target_id = :task_id"),
                    {"task_id": task_id},
                )
                await connection.execute(
                    text("DELETE FROM tasks WHERE id = :task_id"), {"task_id": task_id}
                )
        await app.state.container.database.dispose()


async def test_thing_context_entry_api_replays_and_enforces_version() -> None:
    app = create_app()
    headers = {"Authorization": "Bearer change-me"}
    thing_id: UUID | None = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=headers
        ) as client:
            created = await client.post(
                "/api/v1/things",
                headers={"Idempotency-Key": f"context-thing-{uuid4()}"},
                json={"name": "Context entry integration"},
            )
            assert created.status_code == 201
            thing_id = UUID(created.json()["id"])
            payload = {
                "label": "Advisor focus",
                "content": "Finish the runnable demo first.",
                "reason": "integration test",
            }
            key = f"context-entry-{uuid4()}"
            first = await client.put(
                f"/api/v1/things/{thing_id}/context",
                headers={"Idempotency-Key": key}, json=payload
            )
            replay = await client.put(
                f"/api/v1/things/{thing_id}/context",
                headers={"Idempotency-Key": key}, json=payload
            )
            assert first.status_code == 200
            assert replay.json()["replayed"] is True
            entry_id = first.json()["target_id"]
            entries = await client.get(f"/api/v1/things/{thing_id}/context")
            assert entries.status_code == 200
            assert entries.json()[0]["content"] == payload["content"]

            updated = await client.put(
                f"/api/v1/things/{thing_id}/context",
                headers={"Idempotency-Key": f"context-update-{uuid4()}"},
                json={
                    **payload,
                    "entry_id": entry_id,
                    "expected_version": 1,
                    "content": "Finish the tested demo first.",
                },
            )
            stale = await client.put(
                f"/api/v1/things/{thing_id}/context",
                headers={"Idempotency-Key": f"context-stale-{uuid4()}"},
                json={**payload, "entry_id": entry_id, "expected_version": 1},
            )
            assert updated.status_code == 200
            assert updated.json()["target_version"] == 2
            assert stale.status_code == 409
            assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
    finally:
        if thing_id is not None:
            database = app.state.container.database
            async with database.engine.begin() as connection:
                for statement in (
                    "DELETE FROM timeline_events WHERE thing_id = :thing_id",
                    "DELETE FROM state_mutations WHERE thing_id = :thing_id",
                    "DELETE FROM thing_context_entries WHERE thing_id = :thing_id",
                    "DELETE FROM things WHERE id = :thing_id",
                ):
                    await connection.execute(text(statement), {"thing_id": thing_id})
        await app.state.container.database.dispose()


async def test_merge_redirect_rebinds_current_task_and_hides_duplicate() -> None:
    app = create_app()
    headers = {"Authorization": "Bearer change-me"}
    thing_ids: list[UUID] = []
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=headers
        ) as client:
            canonical = await client.post(
                "/api/v1/things",
                headers={"Idempotency-Key": f"merge-canonical-{uuid4()}"},
                json={"name": "Canonical project"},
            )
            duplicate = await client.post(
                "/api/v1/things",
                headers={"Idempotency-Key": f"merge-duplicate-{uuid4()}"},
                json={"name": "Duplicate project"},
            )
            assert canonical.status_code == duplicate.status_code == 201
            canonical_id = UUID(canonical.json()["id"])
            duplicate_id = UUID(duplicate.json()["id"])
            thing_ids.extend((canonical_id, duplicate_id))
            task = await client.post(
                f"/api/v1/things/{duplicate_id}/tasks",
                headers={"Idempotency-Key": f"merge-task-{uuid4()}"},
                json={"title": "Current task must follow canonical"},
            )
            assert task.status_code == 201

            merged = await client.post(
                f"/api/v1/things/{canonical_id}/merge",
                headers={"Idempotency-Key": f"merge-{uuid4()}"},
                json={
                    "duplicate_thing_id": str(duplicate_id),
                    "expected_canonical_version": 1,
                    "expected_duplicate_version": 1,
                    "reason": "integration merge",
                },
            )
            assert merged.status_code == 200
            assert merged.json()["target_id"] == str(duplicate_id)
            tasks = await client.get(f"/api/v1/things/{canonical_id}/tasks")
            listed = await client.get("/api/v1/things", params={"q": "project"})
            duplicate_view = await client.get(f"/api/v1/things/{duplicate_id}")
            assert tasks.status_code == 200
            assert tasks.json()[0]["id"] == task.json()["id"]
            assert [item["id"] for item in listed.json()] == [str(canonical_id)]
            assert duplicate_view.json()["merged_into_thing_id"] == str(canonical_id)
    finally:
        if thing_ids:
            database = app.state.container.database
            async with database.engine.begin() as connection:
                for table in ("timeline_events", "state_mutations", "tasks", "things"):
                    await connection.execute(
                        text(f"DELETE FROM {table} WHERE thing_id = ANY(:thing_ids)")
                        if table != "things"
                        else text("DELETE FROM things WHERE id = ANY(:thing_ids)"),
                        {"thing_ids": thing_ids},
                    )
        await app.state.container.database.dispose()


async def test_product_api_error_contract() -> None:
    app = create_app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
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
