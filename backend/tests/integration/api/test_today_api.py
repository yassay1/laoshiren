import os
from uuid import UUID, uuid4

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


async def test_today_api_aggregates_attention_and_overview() -> None:
    app = create_app()
    token = app.state.container.settings.dev_auth_token
    user_id = app.state.container.settings.dev_user_id
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=headers,
        ) as client:
            await app.state.container.personal_state.create_thing(
                user_id=UUID(user_id),
                name="Today 聚合测试",
                action_id="api.today",
                idempotency_key=f"today-thing-{uuid4()}",
                reason="Today API test",
            )
            response = await client.get("/api/v1/today")
            assert response.status_code == 200
            payload = response.json()
            assert "attention" in payload
            assert "upcoming" in payload
            assert "overdue" in payload
            assert "due_today" in payload
            assert "blocked" in payload
            assert "active" in payload
            assert "recent" in payload
            assert "generated_at" in payload
    finally:
        await app.state.container.database.dispose()
