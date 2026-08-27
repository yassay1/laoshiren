import os
from uuid import UUID, uuid4

import pytest

from laoshiren.application.personal_state.service import PersonalStateApplicationService
from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def test_agent_thing_prefetch_resolves_active_thread_thing() -> None:
    app = create_app()
    container = app.state.container
    user_id = UUID(container.settings.dev_user_id)
    service: PersonalStateApplicationService = container.personal_state
    thing = await service.create_thing(
        user_id=user_id,
        name="鸿蒙比赛",
        action_id="test.prefetch",
        idempotency_key=f"prefetch-thing-{uuid4()}",
        reason="test",
    )
    await service.create_task(
        user_id=user_id,
        thing_id=thing.id,
        title="提交 Demo",
        action_id="test.prefetch",
        idempotency_key=f"prefetch-task-{uuid4()}",
        reason="test",
    )
    payload = await service.get_agent_thing_prefetch(
        user_id=user_id,
        active_thing_id=thing.id,
    )
    assert payload["match_status"] == "resolved"
    assert payload["thing"]["name"] == "鸿蒙比赛"
    assert payload["open_tasks"][0]["title"] == "提交 Demo"


async def test_agent_thing_prefetch_marks_query_ambiguity() -> None:
    app = create_app()
    container = app.state.container
    uid = UUID(container.settings.dev_user_id)
    service = container.personal_state
    for index in range(2):
        await service.create_thing(
            user_id=uid,
            name=f"Demo 项目 {index}",
            action_id="test.prefetch",
            idempotency_key=f"prefetch-dup-{index}-{uuid4()}",
            reason="test",
        )
    payload = await service.get_agent_thing_prefetch(
        user_id=uid,
        query="Demo 项目",
    )
    assert payload["match_status"] == "ambiguous"
    assert len(payload["candidates"]) >= 2
