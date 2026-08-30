"""NotificationIntent + Delivery creation from settled Occurrences."""

from uuid import UUID

from laoshiren.application.automations.materialize import scheduled_slot_key
from laoshiren.application.automations.ports import AutomationUnitOfWork
from laoshiren.domain.automations.entities import (
    Automation,
    AutomationOccurrence,
    NotificationDelivery,
    NotificationIntent,
)
from laoshiren.domain.automations.value_objects import NotificationKind
from laoshiren.domain.runtime.entities import DurableJob, DurableJobKind


def push_delivery_dedupe_key(delivery_id: UUID) -> str:
    return f"PUSH_DELIVERY:{delivery_id}"


async def create_reminder_notification(
    uow: AutomationUnitOfWork,
    *,
    automation: Automation,
    occurrence: AutomationOccurrence,
) -> NotificationIntent | None:
    dedupe_key = scheduled_slot_key(
        automation_id=automation.id,
        definition_revision=occurrence.definition_revision,
        scheduled_for=occurrence.scheduled_for,
    )
    existing = await uow.notification_intents.get_by_dedupe_key(dedupe_key=dedupe_key)
    if existing is not None:
        return existing

    intent = NotificationIntent(
        user_id=automation.user_id,
        kind=NotificationKind.REMINDER,
        title=automation.title,
        body=automation.message,
        occurrence_id=occurrence.id,
        automation_id=automation.id,
        thing_id=automation.thing_id,
        dedupe_key=dedupe_key,
    )
    if not await uow.notification_intents.add(intent):
        return await uow.notification_intents.get_by_dedupe_key(dedupe_key=dedupe_key)

    endpoints = await uow.push_endpoints.list_eligible(user_id=automation.user_id)
    for endpoint in endpoints:
        delivery = NotificationDelivery(
            user_id=automation.user_id,
            intent_id=intent.id,
            endpoint_id=endpoint.id,
        )
        if not await uow.notification_deliveries.add(delivery):
            continue
        await uow.durable_jobs.add(
            DurableJob(
                user_id=automation.user_id,
                kind=DurableJobKind.PUSH_DELIVERY,
                dedupe_key=push_delivery_dedupe_key(delivery.id),
                payload={
                    "delivery_id": str(delivery.id),
                    "intent_id": str(intent.id),
                    "endpoint_id": str(endpoint.id),
                },
            )
        )
    return intent
