from uuid import UUID

from laoshiren.application.runtime.service import RuntimeApplicationService
from laoshiren.domain.automations.entities import NotificationOutbox


class RuntimeAutomationRunTrigger:
    """Adapter: due Automation notifications enqueue Executive Agent Runs."""

    def __init__(self, runtime: RuntimeApplicationService) -> None:
        self._runtime = runtime

    async def trigger_from_notification(self, *, notification: NotificationOutbox) -> UUID | None:
        run = await self._runtime.create_automation_run(
            user_id=notification.user_id,
            automation_id=notification.automation_id,
            thing_id=notification.thing_id,
            title=notification.title,
            message=notification.message,
            occurrence_key=notification.occurrence_key,
        )
        return run.id
