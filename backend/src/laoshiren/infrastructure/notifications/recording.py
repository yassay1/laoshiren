from laoshiren.domain.automations.entities import NotificationOutbox


class RecordingNotificationAdapter:
    """Accepts submissions for tests/dev without claiming device delivery."""

    def __init__(self) -> None:
        self.submitted_ids: list[str] = []
        self.submitted_keys: set[str] = set()

    async def submit(
        self, notification: NotificationOutbox, *, idempotency_key: str
    ) -> bool:
        if not idempotency_key.strip():
            raise ValueError("Notification idempotency key is required.")
        if idempotency_key in self.submitted_keys:
            return True
        self.submitted_keys.add(idempotency_key)
        self.submitted_ids.append(str(notification.id))
        return True
