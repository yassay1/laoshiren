import logging

from fastapi import Request, Response
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class RedisRateLimitMiddleware(BaseHTTPMiddleware):
    """Best-effort per-IP rate limiting; fails open when Redis is unavailable."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        redis_url: str,
        enabled: bool,
        requests_per_minute: int,
    ) -> None:
        super().__init__(app)
        self._enabled = enabled and requests_per_minute > 0
        self._limit = requests_per_minute
        self._client: Redis | None = (
            Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=0.2,
                socket_timeout=0.2,
            )
            if self._enabled
            else None
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self._client is None or request.url.path.endswith("/health/ready"):
            return await call_next(request)
        client_host = request.client.host if request.client is not None else "unknown"
        key = f"rate-limit:{client_host}:{request.url.path}"
        try:
            count = await self._client.incr(key)
            if count == 1:
                await self._client.expire(key, 60)
            if count > self._limit:
                return Response(status_code=429, content="Rate limit exceeded.")
        except RedisError:
            logger.warning("redis_rate_limit_failed", exc_info=True)
        return await call_next(request)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
