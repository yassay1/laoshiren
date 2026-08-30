import asyncio
import json
import logging
from uuid import UUID

from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from redis.exceptions import RedisError

from laoshiren.application.runtime.dto import EphemeralFrameDTO

logger = logging.getLogger(__name__)


class RedisRuntimeLiveSubscription:
    def __init__(self, *, run_id: UUID, pubsub: PubSub) -> None:
        self._run_id = run_id
        self._pubsub = pubsub

    async def wait(self, *, timeout_seconds: float) -> EphemeralFrameDTO | None:
        try:
            async with asyncio.timeout(timeout_seconds):
                while True:
                    message = await self._pubsub.get_message(ignore_subscribe_messages=True)
                    if message is not None:
                        try:
                            payload = json.loads(str(message["data"]))
                        except (KeyError, TypeError, json.JSONDecodeError):
                            logger.warning("redis_runtime_malformed_message", exc_info=True)
                            continue
                        if not isinstance(payload, dict):
                            logger.warning("redis_runtime_invalid_payload_type")
                            continue
                        if payload.get("kind") == "FRAME":
                            frame_type = payload.get("frame_type")
                            data = payload.get("data", {})
                            if not isinstance(frame_type, str) or not isinstance(data, dict):
                                logger.warning("redis_runtime_invalid_frame_payload")
                                continue
                            return EphemeralFrameDTO(
                                run_id=self._run_id,
                                frame_type=frame_type,
                                data=data,
                            )
                        return None
                    await asyncio.sleep(0.01)
        except TimeoutError:
            return None
        except RedisError:
            logger.warning("redis_runtime_wakeup_wait_failed", exc_info=True)
            return None

    async def close(self) -> None:
        await self._pubsub.aclose()  # type: ignore[no-untyped-call]


class RedisRuntimeWakeup:
    """Best-effort Run wake-ups; PostgreSQL polling remains authoritative."""

    def __init__(self, url: str, *, enabled: bool = True) -> None:
        self._client: Redis | None = (
            Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=0.2,
                socket_timeout=0.5,
            )
            if enabled
            else None
        )

    @staticmethod
    def _channel(run_id: UUID) -> str:
        return f"runtime:run:{run_id}:events"

    async def publish(self, *, run_id: UUID, latest_sequence: int) -> None:
        if self._client is None:
            return
        try:
            await self._client.publish(
                self._channel(run_id),
                json.dumps({"kind": "WAKEUP", "latest_sequence": latest_sequence}),
            )
        except RedisError:
            logger.warning("redis_runtime_wakeup_publish_failed", exc_info=True)

    async def publish_frame(self, frame: EphemeralFrameDTO) -> None:
        if self._client is None:
            return
        payload = {
            "kind": "FRAME",
            "frame_type": frame.frame_type,
            "data": frame.data,
            "emitted_at": frame.emitted_at.isoformat(),
        }
        try:
            await self._client.publish(self._channel(frame.run_id), json.dumps(payload))
        except RedisError:
            logger.warning("redis_runtime_frame_publish_failed", exc_info=True)

    async def subscribe(self, *, run_id: UUID) -> RedisRuntimeLiveSubscription | None:
        if self._client is None:
            return None
        pubsub = self._client.pubsub()
        try:
            await pubsub.subscribe(self._channel(run_id))
        except RedisError:
            logger.warning("redis_runtime_subscribe_failed", exc_info=True)
            await pubsub.aclose()  # type: ignore[no-untyped-call]
            return None
        return RedisRuntimeLiveSubscription(run_id=run_id, pubsub=pubsub)

    async def wait(self, *, run_id: UUID, timeout_seconds: float) -> EphemeralFrameDTO | None:
        subscription = await self.subscribe(run_id=run_id)
        if subscription is None:
            await asyncio.sleep(timeout_seconds)
            return None
        try:
            return await subscription.wait(timeout_seconds=timeout_seconds)
        finally:
            await subscription.close()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
