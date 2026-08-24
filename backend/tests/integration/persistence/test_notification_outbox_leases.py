import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from laoshiren.application.automations.service import AutomationApplicationService
from laoshiren.domain.automations.entities import AutomationType, NotificationOutbox
from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


class SequenceNotificationAdapter:
    def __init__(self, results: list[bool]) -> None:
        self.results = results
        self.calls: list[UUID] = []

    async def submit(self, notification: NotificationOutbox) -> bool:
        self.calls.append(notification.id)
        return self.results.pop(0)


async def test_outbox_retry_is_due_gated_and_concurrent_claim_is_exclusive() -> None:
    app = create_app()
    container = app.state.container
    user_id = UUID(container.settings.dev_user_id)
    automation_id = None
    adapter = SequenceNotificationAdapter([False, True])
    service_a = AutomationApplicationService(
        container.database.automation_unit_of_work, adapter
    )
    service_b = AutomationApplicationService(
        container.database.automation_unit_of_work, adapter
    )
    try:
        automation = await service_a.create(
            user_id=user_id,
            automation_type=AutomationType.ONE_SHOT,
            title="durable outbox",
            message="retry me",
            timezone_name="UTC",
            next_trigger_at=datetime.now(UTC) - timedelta(seconds=1),
            idempotency_key=f"outbox-{uuid4()}",
        )
        automation_id = automation.id
        assert await service_a.process_due() == 1

        first = await service_a.dispatch_pending(
            retry_base_seconds=60, retry_max_seconds=60
        )
        immediate = await service_b.dispatch_pending()
        assert first == 0
        assert immediate == 0
        assert len(adapter.calls) == 1

        async with container.database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE notification_outbox SET next_attempt_at = :due "
                    "WHERE automation_id = :automation_id"
                ),
                {
                    "due": datetime.now(UTC) - timedelta(seconds=1),
                    "automation_id": automation.id,
                },
            )

        dispatched_a, dispatched_b = await asyncio.gather(
            service_a.dispatch_pending(), service_b.dispatch_pending()
        )
        assert dispatched_a + dispatched_b == 1
        assert len(adapter.calls) == 2

        async with container.database.engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT status, attempt_count, claim_owner, next_attempt_at "
                        "FROM notification_outbox WHERE automation_id = :automation_id"
                    ),
                    {"automation_id": automation.id},
                )
            ).one()
        assert row.status == "SUBMITTED_TO_ADAPTER"
        assert row.attempt_count == 2
        assert row.claim_owner is None
        assert row.next_attempt_at is None
    finally:
        if automation_id is not None:
            async with container.database.engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM notification_outbox WHERE automation_id = :id"),
                    {"id": automation_id},
                )
                await connection.execute(
                    text("DELETE FROM automations WHERE id = :id"),
                    {"id": automation_id},
                )
        await container.database.dispose()
