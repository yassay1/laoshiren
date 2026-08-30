from laoshiren.domain.automations.entities import (
    NotificationDelivery,
    NotificationIntent,
    NotificationOutbox,
    PushEndpoint,
)


class RecordingNotificationAdapter:
    """Accepts submissions for tests/dev without claiming device delivery."""

    def __init__(self) -> None:
        self.submitted_ids: list[str] = []
        self.submitted_keys: set[str] = set()
        self.delivery_keys: set[str] = set()

    async def submit(self, notification: NotificationOutbox, *, idempotency_key: str) -> bool:
        if not idempotency_key.strip():
            raise ValueError("Notification idempotency key is required.")
        if idempotency_key in self.submitted_keys:
            return True
        self.submitted_keys.add(idempotency_key)
        self.submitted_ids.append(str(notification.id))
        return True

    async def submit_delivery(
        self,
        *,
        delivery: NotificationDelivery,
        intent: NotificationIntent,
        endpoint: PushEndpoint,
        idempotency_key: str,
    ) -> bool:
        del intent, endpoint
        if not idempotency_key.strip():
            raise ValueError("Push delivery idempotency key is required.")
        if idempotency_key in self.delivery_keys:
            return True
        self.delivery_keys.add(idempotency_key)
        self.submitted_ids.append(str(delivery.id))
        return True
