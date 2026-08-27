from uuid import uuid4

import pytest

from laoshiren.application.automations.service import AutomationApplicationService
from laoshiren.domain.automations.entities import (
    NotificationOutbox,
)


class RecordingRunTrigger:
    def __init__(self) -> None:
        self.calls: list[NotificationOutbox] = []

    async def trigger_from_notification(self, *, notification: NotificationOutbox):
        self.calls.append(notification)
        return uuid4()


class RecordingNotificationPort:
    async def submit(self, notification: NotificationOutbox, *, idempotency_key: str) -> bool:
        return True


class EmptyUow:
    notifications: object

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class NotificationRepo:
    def __init__(self, item: NotificationOutbox | None) -> None:
        self._item = item
        self.completed = False

    async def claim_next(self, **kwargs):
        return self._item

    async def complete(self, *, notification, owner):
        self.completed = True
        return True


@pytest.mark.asyncio
async def test_dispatch_pending_triggers_agent_run_before_notification() -> None:
    notification = NotificationOutbox(
        user_id=uuid4(),
        automation_id=uuid4(),
        occurrence_key="occ-1",
        title="提醒",
        message="该提交了",
    )
    uow = EmptyUow()
    uow.notifications = NotificationRepo(notification)
    trigger = RecordingRunTrigger()
    service = AutomationApplicationService(
        lambda: uow,
        RecordingNotificationPort(),
        run_trigger=trigger,
    )

    submitted = await service.dispatch_pending(limit=1)

    assert submitted == 1
    assert len(trigger.calls) == 1
    assert trigger.calls[0].occurrence_key == "occ-1"
    assert uow.notifications.completed is True


@pytest.mark.asyncio
async def test_dispatch_pending_counts_run_when_notification_rejected() -> None:
    notification = NotificationOutbox(
        user_id=uuid4(),
        automation_id=uuid4(),
        occurrence_key="occ-2",
        title="提醒",
        message="该检查了",
    )
    uow = EmptyUow()
    uow.notifications = NotificationRepo(notification)
    trigger = RecordingRunTrigger()

    class RejectPort:
        async def submit(self, notification, *, idempotency_key: str) -> bool:
            return False

    service = AutomationApplicationService(lambda: uow, RejectPort(), run_trigger=trigger)
    submitted = await service.dispatch_pending(limit=1)
    assert submitted == 1
    assert len(trigger.calls) == 1
