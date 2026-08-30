import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from laoshiren.domain.runtime.entities import RunStatus, RunTrigger
from laoshiren.infrastructure.automation.run_trigger import RuntimeAutomationRunTrigger
from laoshiren.main import create_app
from laoshiren.workers.automation import run_once
from laoshiren.workers.automation_occurrence import AutomationOccurrenceWorker
from laoshiren.workers.push_delivery import PushDeliveryWorker

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def test_automation_dispatch_triggers_agent_run() -> None:
    app = create_app()
    container = app.state.container
    user_id = UUID(container.settings.dev_user_id)
    headers = {"Authorization": "Bearer change-me"}
    now = datetime.now(UTC)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers
    ) as client:
        thing = await client.post(
            "/api/v1/things",
            headers={"Idempotency-Key": f"auto-run-{uuid4()}"},
            json={"name": "自动化 Agent Run 测试"},
        )
        assert thing.status_code == 201
        thing_id = thing.json()["id"]
        create = await client.post(
            "/api/v1/automations",
            headers={"Idempotency-Key": f"auto-run-{uuid4()}"},
            json={
                "automation_type": "ONE_SHOT",
                "title": "检查提交",
                "message": "提醒用户检查材料是否已提交",
                "timezone": "Asia/Shanghai",
                "next_trigger_at": (now - timedelta(minutes=1)).isoformat(),
                "thing_id": thing_id,
            },
        )
        assert create.status_code == 201

    occurrence_worker = AutomationOccurrenceWorker(
        container.database.automation_unit_of_work,
        run_trigger=RuntimeAutomationRunTrigger(container.runtime),
    )
    push_worker = PushDeliveryWorker(
        container.database.automation_unit_of_work,
        container.notification_adapter,
    )
    generated, processed = await run_once(
        container.automations,
        occurrence_worker,
        push_worker,
        limit=10,
    )
    assert generated >= 1
    assert processed >= 1

    threads = await container.runtime.list_threads(user_id=user_id, limit=50)
    automation_threads = [item for item in threads if item.title == "自动化"]
    assert automation_threads

    from sqlalchemy import select

    from laoshiren.infrastructure.persistence.orm.personal_state import AgentRunORM

    async with container.database.session_factory() as session:
        result = await session.scalars(
            select(AgentRunORM).where(
                AgentRunORM.user_id == user_id,
                AgentRunORM.trigger == RunTrigger.AUTOMATION,
            )
        )
        runs = result.all()
    assert runs
    assert runs[0].status in {
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        RunStatus.COMPLETED,
        RunStatus.WAITING_FOR_USER,
    }
