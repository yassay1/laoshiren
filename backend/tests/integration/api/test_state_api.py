import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def test_state_overview_api() -> None:
    app = create_app()
    token = app.state.container.settings.dev_auth_token
    headers = {"Authorization": f"Bearer {token}"}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/state/overview", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert "upcoming" in body
    assert "blocked" in body
    assert "active" in body
    assert "recent" in body


async def test_archive_thing_api() -> None:
    app = create_app()
    token = app.state.container.settings.dev_auth_token
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": f"archive-test-{uuid4()}",
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/things",
            headers=headers,
            json={"name": "待归档事项"},
        )
        assert created.status_code == 201
        thing = created.json()
        archive = await client.post(
            f"/api/v1/things/{thing['id']}/archive",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"archive-{uuid4()}"},
            json={"expected_version": thing["version"], "reason": "测试归档"},
        )
    assert archive.status_code == 200
    assert archive.json()["target_id"] == thing["id"]
