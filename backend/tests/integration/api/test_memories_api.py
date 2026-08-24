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


async def test_memory_product_api_lifecycle() -> None:
    app = create_app()
    headers = {"Authorization": "Bearer change-me"}
    memory_id: UUID | None = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=headers
        ) as client:
            create_key = f"memory-test-{uuid4()}"
            payload = {
                "memory_type": "SEMANTIC",
                "content": "老实人客户端采用 ArkTS 与 ArkUI。",
                "summary": "客户端技术路线",
                "importance": 0.9,
                "confidence": 1,
            }
            created = await client.post(
                "/api/v1/memories",
                headers={"Idempotency-Key": create_key},
                json=payload,
            )
            replay_create = await client.post(
                "/api/v1/memories",
                headers={"Idempotency-Key": create_key},
                json=payload,
            )
            assert created.status_code == 201
            assert replay_create.json()["replayed"] is True
            memory_id = UUID(created.json()["id"])

            searched = await client.get(
                "/api/v1/memories", params={"q": "ArkUI", "memory_type": "SEMANTIC"}
            )
            assert searched.status_code == 200
            assert [item["id"] for item in searched.json()] == [str(memory_id)]

            update_key = f"memory-test-{uuid4()}"
            update_payload = {
                "summary": "HarmonyOS 客户端技术路线",
                "importance": 1,
                "expected_version": 1,
            }
            updated = await client.patch(
                f"/api/v1/memories/{memory_id}",
                headers={"Idempotency-Key": update_key},
                json=update_payload,
            )
            replay_update = await client.patch(
                f"/api/v1/memories/{memory_id}",
                headers={"Idempotency-Key": update_key},
                json=update_payload,
            )
            conflict = await client.patch(
                f"/api/v1/memories/{memory_id}",
                headers={"Idempotency-Key": f"memory-test-{uuid4()}"},
                json={"summary": "stale", "expected_version": 1},
            )
            assert updated.status_code == 200
            assert updated.json()["version"] == 2
            assert replay_update.status_code == 200
            assert replay_update.json()["replayed"] is True
            assert conflict.status_code == 409

            superseded = await client.patch(
                f"/api/v1/memories/{memory_id}",
                headers={"Idempotency-Key": f"memory-test-{uuid4()}"},
                json={"supersede": True, "expected_version": 2},
            )
            active_search = await client.get("/api/v1/memories", params={"q": "ArkUI"})
            fetched = await client.get(f"/api/v1/memories/{memory_id}")
            assert superseded.json()["status"] == "SUPERSEDED"
            assert superseded.json()["version"] == 3
            assert active_search.json() == []
            assert fetched.json()["status"] == "SUPERSEDED"

            delete_key = f"memory-test-{uuid4()}"
            deleted = await client.delete(
                f"/api/v1/memories/{memory_id}",
                headers={"Idempotency-Key": delete_key},
                params={"expected_version": 3},
            )
            replay_delete = await client.delete(
                f"/api/v1/memories/{memory_id}",
                headers={"Idempotency-Key": delete_key},
                params={"expected_version": 3},
            )
            assert deleted.status_code == 200
            assert deleted.json()["status"] == "DELETED"
            assert deleted.json()["version"] == 4
            assert replay_delete.status_code == 200
            assert replay_delete.json()["replayed"] is True
    finally:
        if memory_id is not None:
            async with app.state.container.database.engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM memory_operations WHERE memory_id = :memory_id"),
                    {"memory_id": memory_id},
                )
                await connection.execute(
                    text("DELETE FROM long_term_memories WHERE id = :memory_id"),
                    {"memory_id": memory_id},
                )
        await app.state.container.database.dispose()
