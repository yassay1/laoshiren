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


async def test_personal_state_completion_flow() -> None:
    app = create_app()
    headers = {"Authorization": "Bearer change-me"}
    thing_ids: list[UUID] = []
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=headers
        ) as client:
            for name in ("批次十主事务", "批次十关联事务"):
                response = await client.post(
                    "/api/v1/things",
                    headers={"Idempotency-Key": f"completion-{uuid4()}"},
                    json={"name": name},
                )
                assert response.status_code == 201
                thing_ids.append(UUID(response.json()["id"]))
            thing_id, related_id = thing_ids

            filtered = await client.get(
                "/api/v1/things", params={"q": "批次十", "status": "PLANNING", "limit": 10}
            )
            assert filtered.status_code == 200
            assert {UUID(item["id"]) for item in filtered.json()}.issuperset(thing_ids)

            task_response = await client.post(
                f"/api/v1/things/{thing_id}/tasks",
                headers={"Idempotency-Key": f"completion-{uuid4()}"},
                json={"title": "验证完整状态机"},
            )
            task_id = task_response.json()["id"]
            version = 1
            for target in ("IN_PROGRESS", "BLOCKED", "DONE"):
                transitioned = await client.patch(
                    f"/api/v1/tasks/{task_id}",
                    headers={"Idempotency-Key": f"completion-{uuid4()}"},
                    json={
                        "status": target,
                        "expected_version": version,
                        "reason": "State machine integration test",
                    },
                )
                assert transitioned.status_code == 200
                version += 1
                assert transitioned.json()["target_version"] == version
            illegal = await client.patch(
                f"/api/v1/tasks/{task_id}",
                headers={"Idempotency-Key": f"completion-{uuid4()}"},
                json={"status": "WAITING", "expected_version": 4, "reason": "illegal"},
            )
            reopened = await client.patch(
                f"/api/v1/tasks/{task_id}",
                headers={"Idempotency-Key": f"completion-{uuid4()}"},
                json={"status": "TODO", "expected_version": 4, "reason": "reopen"},
            )
            assert illegal.status_code == 409
            assert illegal.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
            assert reopened.status_code == 200
            assert reopened.json()["target_version"] == 5

            date_response = await client.post(
                f"/api/v1/things/{thing_id}/dates",
                headers={"Idempotency-Key": f"completion-{uuid4()}"},
                json={
                    "kind": "SUBMISSION_DEADLINE",
                    "value": "2026-09-01T18:00:00+08:00",
                    "timezone": "Asia/Shanghai",
                    "precision": "DATETIME",
                    "certainty": "CONFIRMED",
                    "is_primary": True,
                    "expected_version": 1,
                    "reason": "Create date",
                },
            )
            date_id = date_response.json()["target_id"]
            updated_date = await client.patch(
                f"/api/v1/thing-dates/{date_id}",
                headers={"Idempotency-Key": f"completion-{uuid4()}"},
                json={
                    "value": "2026-09-02T18:00:00+08:00",
                    "timezone": "Asia/Shanghai",
                    "precision": "DATETIME",
                    "certainty": "CONFIRMED",
                    "is_primary": True,
                    "expected_version": 1,
                    "expected_thing_version": 2,
                    "reason": "Update date",
                },
            )
            dates = await client.get(f"/api/v1/things/{thing_id}/dates")
            assert updated_date.status_code == 200
            assert updated_date.json()["target_version"] == 2
            assert dates.json()[0]["version"] == 2
            assert dates.json()[0]["value"] == "2026-09-02T10:00:00Z"

            blocker_key = f"completion-{uuid4()}"
            blocker_response = await client.post(
                f"/api/v1/things/{thing_id}/blockers",
                headers={"Idempotency-Key": blocker_key},
                json={
                    "description": "等待外部确认",
                    "severity": "HIGH",
                    "task_id": task_id,
                    "reason": "Create blocker",
                },
            )
            replay_blocker = await client.post(
                f"/api/v1/things/{thing_id}/blockers",
                headers={"Idempotency-Key": blocker_key},
                json={
                    "description": "等待外部确认",
                    "severity": "HIGH",
                    "task_id": task_id,
                    "reason": "Replay blocker",
                },
            )
            blocker_id = blocker_response.json()["id"]
            resolved = await client.post(
                f"/api/v1/blockers/{blocker_id}/resolve",
                headers={"Idempotency-Key": f"completion-{uuid4()}"},
                json={"expected_version": 1, "reason": "Resolved"},
            )
            blockers = await client.get(f"/api/v1/things/{thing_id}/blockers")
            assert blocker_response.status_code == 201
            assert replay_blocker.json()["id"] == blocker_id
            assert resolved.json()["target_version"] == 2
            assert blockers.json()[0]["status"] == "RESOLVED"

            relation_key = f"completion-{uuid4()}"
            relation_payload = {
                "to_thing_id": str(related_id),
                "relation_type": "DEPENDS_ON",
                "note": "集成测试依赖",
                "reason": "Create relation",
            }
            relation = await client.post(
                f"/api/v1/things/{thing_id}/relations",
                headers={"Idempotency-Key": relation_key},
                json=relation_payload,
            )
            replay_relation = await client.post(
                f"/api/v1/things/{thing_id}/relations",
                headers={"Idempotency-Key": relation_key},
                json=relation_payload,
            )
            relations = await client.get(f"/api/v1/things/{thing_id}/relations")
            history = await client.get(f"/api/v1/things/{thing_id}/history")
            assert relation.json() == {"created": True}
            assert replay_relation.json() == {"created": False}
            assert relations.json()[0]["to_thing_id"] == str(related_id)
            assert any(item["mutation_type"] == "BLOCKER_RESOLVED" for item in history.json())
            assert all("idempotency_key" not in item for item in history.json())
    finally:
        if thing_ids:
            async with app.state.container.database.engine.begin() as connection:
                for statement in (
                    "DELETE FROM timeline_events WHERE thing_id = ANY(:thing_ids)",
                    "DELETE FROM state_mutations WHERE thing_id = ANY(:thing_ids)",
                    "DELETE FROM blockers WHERE thing_id = ANY(:thing_ids)",
                    "DELETE FROM thing_relations "
                    "WHERE from_thing_id = ANY(:thing_ids) OR to_thing_id = ANY(:thing_ids)",
                    "DELETE FROM tasks WHERE thing_id = ANY(:thing_ids)",
                    "DELETE FROM thing_dates WHERE thing_id = ANY(:thing_ids)",
                    "DELETE FROM things WHERE id = ANY(:thing_ids)",
                ):
                    await connection.execute(text(statement), {"thing_ids": thing_ids})
        await app.state.container.database.dispose()
