import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

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


async def test_version_conflict_blocks_silent_thing_overwrite() -> None:
    app = create_app()
    headers = {"Authorization": "Bearer change-me"}

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=headers,
        ) as client:
            create = await client.post(
                "/api/v1/things",
                headers={"Idempotency-Key": f"gate-b-{uuid4()}"},
                json={"name": "Gate B thing"},
            )
            assert create.status_code == 201
            thing_id = create.json()["id"]

            stale = await client.patch(
                f"/api/v1/things/{thing_id}",
                headers={"Idempotency-Key": f"gate-b-stale-{uuid4()}"},
                json={
                    "name": "stale write",
                    "expected_version": 1,
                    "reason": "gate b first write",
                },
            )
            assert stale.status_code == 200

            conflict = await client.patch(
                f"/api/v1/things/{thing_id}",
                headers={"Idempotency-Key": f"gate-b-conflict-{uuid4()}"},
                json={
                    "name": "should fail",
                    "expected_version": 1,
                    "reason": "gate b conflict attempt",
                },
            )
            assert conflict.status_code == 409

            current = await client.get(f"/api/v1/things/{thing_id}")
            assert current.status_code == 200
            assert current.json()["name"] == "stale write"
            assert current.json()["version"] == 2
    finally:
        await app.state.container.database.dispose()
