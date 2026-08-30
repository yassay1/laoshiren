import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from laoshiren.infrastructure.coordination.redis_rate_limit import RedisRateLimitMiddleware


async def homepage(_: object) -> PlainTextResponse:
    return PlainTextResponse("ok")


@pytest.mark.asyncio
@pytest.mark.gate_c
async def test_rate_limit_middleware_fails_open_when_redis_unavailable() -> None:
    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(
        RedisRateLimitMiddleware,
        redis_url="redis://127.0.0.1:6399/0",
        enabled=True,
        requests_per_minute=1,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(3):
            response = await client.get("/")
            assert response.status_code == 200
