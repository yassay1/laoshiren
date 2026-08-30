import asyncio
from uuid import uuid4

import pytest

from laoshiren.application.runtime.dto import EphemeralFrameDTO
from laoshiren.infrastructure.coordination.redis_wakeup import RedisRuntimeWakeup


@pytest.mark.asyncio
async def test_disabled_wakeup_degrades_to_timeout_polling() -> None:
    wakeup = RedisRuntimeWakeup("redis://localhost:6379/0", enabled=False)
    assert await wakeup.subscribe(run_id=uuid4()) is None
    assert await wakeup.wait(run_id=uuid4(), timeout_seconds=0.001) is None
    await wakeup.publish(run_id=uuid4(), latest_sequence=1)
    await wakeup.close()


@pytest.mark.asyncio
async def test_redis_wakeup_delivers_only_a_hint() -> None:
    wakeup = RedisRuntimeWakeup("redis://localhost:6379/0")
    run_id = uuid4()
    waiter = asyncio.create_task(wakeup.wait(run_id=run_id, timeout_seconds=1.0))
    await asyncio.sleep(0.05)
    await wakeup.publish(run_id=run_id, latest_sequence=7)
    assert await waiter is None
    await wakeup.close()


@pytest.mark.asyncio
async def test_redis_delivers_ephemeral_frame_without_persistence() -> None:
    wakeup = RedisRuntimeWakeup("redis://localhost:6379/0")
    run_id = uuid4()
    waiter = asyncio.create_task(wakeup.wait(run_id=run_id, timeout_seconds=1.0))
    await asyncio.sleep(0.05)
    await wakeup.publish_frame(
        EphemeralFrameDTO(
            run_id=run_id,
            frame_type="assistant.delta",
            data={"delta": "你好"},
        )
    )
    frame = await waiter
    assert frame is not None
    assert frame.frame_type == "assistant.delta"
    assert frame.data == {"delta": "你好"}
    await wakeup.close()


@pytest.mark.asyncio
async def test_subscription_receives_frame_after_durable_catch_up_window() -> None:
    wakeup = RedisRuntimeWakeup("redis://localhost:6379/0")
    run_id = uuid4()
    subscription = await wakeup.subscribe(run_id=run_id)
    assert subscription is not None
    await wakeup.publish_frame(
        EphemeralFrameDTO(
            run_id=run_id,
            frame_type="assistant.delta",
            data={"delta": "持续"},
        )
    )
    frame = await subscription.wait(timeout_seconds=1.0)
    assert frame is not None
    assert frame.data == {"delta": "持续"}
    await subscription.close()
    await wakeup.close()


@pytest.mark.asyncio
async def test_unavailable_redis_does_not_break_runtime_coordination() -> None:
    wakeup = RedisRuntimeWakeup("redis://127.0.0.1:6399/0")
    await wakeup.publish(run_id=uuid4(), latest_sequence=2)
    assert await wakeup.wait(run_id=uuid4(), timeout_seconds=0.001) is None
    await wakeup.close()
