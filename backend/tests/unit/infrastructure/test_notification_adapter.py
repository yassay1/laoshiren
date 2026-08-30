from uuid import uuid4

import pytest

from laoshiren.domain.automations.entities import NotificationOutbox
from laoshiren.infrastructure.notifications.recording import RecordingNotificationAdapter

pytestmark = pytest.mark.asyncio


async def test_recording_adapter_deduplicates_downstream_submission_key() -> None:
    adapter = RecordingNotificationAdapter()
    notification = NotificationOutbox(
        user_id=uuid4(),
        automation_id=uuid4(),
        occurrence_key="automation:occurrence",
        title="Reminder",
        message="Do the thing",
    )

    first = await adapter.submit(notification, idempotency_key=notification.occurrence_key)
    replay = await adapter.submit(notification, idempotency_key=notification.occurrence_key)

    assert first is True
    assert replay is True
    assert adapter.submitted_ids == [str(notification.id)]
    assert adapter.submitted_keys == {notification.occurrence_key}
