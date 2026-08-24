import pytest
from httpx import ASGITransport, AsyncClient

from laoshiren.main import create_app


@pytest.mark.asyncio
async def test_health_endpoint() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]
    await app.state.container.database.dispose()
