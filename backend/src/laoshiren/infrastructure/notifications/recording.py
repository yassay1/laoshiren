from laoshiren.domain.automations.entities import NotificationOutbox


class RecordingNotificationAdapter:
    """Accepts submissions for tests/dev without claiming device delivery."""

    def __init__(self) -> None:
        self.submitted_ids: list[str] = []

    async def submit(self, notification: NotificationOutbox) -> bool:
        self.submitted_ids.append(str(notification.id))
        return True
