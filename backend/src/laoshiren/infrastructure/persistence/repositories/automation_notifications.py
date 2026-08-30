from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from laoshiren.domain.automations.entities import (
    AutomationOccurrence,
    NotificationDelivery,
    NotificationIntent,
    PushEndpoint,
)
from laoshiren.infrastructure.persistence.orm.personal_state import (
    AutomationOccurrenceORM,
    NotificationDeliveryORM,
    NotificationIntentORM,
    PushEndpointORM,
)


def occurrence_to_domain(model: AutomationOccurrenceORM) -> AutomationOccurrence:
    return AutomationOccurrence(
        id=model.id,
        user_id=model.user_id,
        automation_id=model.automation_id,
        definition_revision=model.definition_revision,
        scheduled_for=model.scheduled_for,
        status=model.status,
        durable_job_id=model.durable_job_id,
        materialized_at=model.materialized_at,
        settled_at=model.settled_at,
        created_at=model.created_at,
    )


def intent_to_domain(model: NotificationIntentORM) -> NotificationIntent:
    return NotificationIntent(
        id=model.id,
        user_id=model.user_id,
        kind=model.kind,
        title=model.title,
        body=model.body,
        occurrence_id=model.occurrence_id,
        automation_id=model.automation_id,
        thing_id=model.thing_id,
        dedupe_key=model.dedupe_key,
        created_at=model.created_at,
    )


def delivery_to_domain(model: NotificationDeliveryORM) -> NotificationDelivery:
    return NotificationDelivery(
        id=model.id,
        user_id=model.user_id,
        intent_id=model.intent_id,
        endpoint_id=model.endpoint_id,
        status=model.status,
        attempt_count=model.attempt_count,
        provider_message_id=model.provider_message_id,
        error_code=model.error_code,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def endpoint_to_domain(model: PushEndpointORM) -> PushEndpoint:
    return PushEndpoint(
        id=model.id,
        user_id=model.user_id,
        device_id=model.device_id,
        push_token=model.push_token,
        provider=model.provider,
        active=model.active,
        notifications_enabled=model.notifications_enabled,
        last_registered_at=model.last_registered_at,
        invalidated_at=model.invalidated_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlAlchemyAutomationOccurrenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, occurrence: AutomationOccurrence) -> bool:
        statement = (
            insert(AutomationOccurrenceORM)
            .values(
                id=occurrence.id,
                user_id=occurrence.user_id,
                automation_id=occurrence.automation_id,
                definition_revision=occurrence.definition_revision,
                scheduled_for=occurrence.scheduled_for,
                status=occurrence.status,
                durable_job_id=occurrence.durable_job_id,
                materialized_at=occurrence.materialized_at,
                settled_at=occurrence.settled_at,
                created_at=occurrence.created_at,
            )
            .on_conflict_do_nothing(
                index_elements=["automation_id", "definition_revision", "scheduled_for"]
            )
            .returning(AutomationOccurrenceORM.id)
        )
        inserted = await self._session.scalar(statement)
        return inserted is not None

    async def get(self, *, occurrence_id: UUID) -> AutomationOccurrence | None:
        model = await self._session.scalar(
            select(AutomationOccurrenceORM).where(AutomationOccurrenceORM.id == occurrence_id)
        )
        return occurrence_to_domain(model) if model is not None else None

    async def update(self, occurrence: AutomationOccurrence) -> None:
        await self._session.execute(
            update(AutomationOccurrenceORM)
            .where(AutomationOccurrenceORM.id == occurrence.id)
            .values(
                status=occurrence.status,
                durable_job_id=occurrence.durable_job_id,
                settled_at=occurrence.settled_at,
            )
        )


class SqlAlchemyNotificationIntentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, intent: NotificationIntent) -> bool:
        statement = (
            insert(NotificationIntentORM)
            .values(
                id=intent.id,
                user_id=intent.user_id,
                kind=intent.kind,
                title=intent.title,
                body=intent.body,
                occurrence_id=intent.occurrence_id,
                automation_id=intent.automation_id,
                thing_id=intent.thing_id,
                dedupe_key=intent.dedupe_key,
                created_at=intent.created_at,
            )
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
            .returning(NotificationIntentORM.id)
        )
        inserted = await self._session.scalar(statement)
        return inserted is not None

    async def get_by_dedupe_key(self, *, dedupe_key: str) -> NotificationIntent | None:
        model = await self._session.scalar(
            select(NotificationIntentORM).where(NotificationIntentORM.dedupe_key == dedupe_key)
        )
        return intent_to_domain(model) if model is not None else None

    async def get(self, *, intent_id: UUID) -> NotificationIntent | None:
        model = await self._session.scalar(
            select(NotificationIntentORM).where(NotificationIntentORM.id == intent_id)
        )
        return intent_to_domain(model) if model is not None else None


class SqlAlchemyNotificationDeliveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, delivery: NotificationDelivery) -> bool:
        statement = (
            insert(NotificationDeliveryORM)
            .values(
                id=delivery.id,
                user_id=delivery.user_id,
                intent_id=delivery.intent_id,
                endpoint_id=delivery.endpoint_id,
                status=delivery.status,
                attempt_count=delivery.attempt_count,
                provider_message_id=delivery.provider_message_id,
                error_code=delivery.error_code,
                created_at=delivery.created_at,
                updated_at=delivery.updated_at,
            )
            .on_conflict_do_nothing(index_elements=["intent_id", "endpoint_id"])
            .returning(NotificationDeliveryORM.id)
        )
        inserted = await self._session.scalar(statement)
        return inserted is not None

    async def get(self, *, delivery_id: UUID) -> NotificationDelivery | None:
        model = await self._session.scalar(
            select(NotificationDeliveryORM).where(NotificationDeliveryORM.id == delivery_id)
        )
        return delivery_to_domain(model) if model is not None else None

    async def update(self, delivery: NotificationDelivery) -> bool:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(NotificationDeliveryORM)
                .where(NotificationDeliveryORM.id == delivery.id)
                .values(
                    status=delivery.status,
                    attempt_count=delivery.attempt_count,
                    provider_message_id=delivery.provider_message_id,
                    error_code=delivery.error_code,
                    updated_at=delivery.updated_at,
                )
            ),
        )
        return result.rowcount == 1


class SqlAlchemyPushEndpointRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_eligible(self, *, user_id: UUID) -> list[PushEndpoint]:
        models = (
            await self._session.scalars(
                select(PushEndpointORM).where(
                    PushEndpointORM.user_id == user_id,
                    PushEndpointORM.active.is_(True),
                    PushEndpointORM.notifications_enabled.is_(True),
                    PushEndpointORM.invalidated_at.is_(None),
                )
            )
        ).all()
        return [endpoint_to_domain(model) for model in models]

    async def get(self, *, endpoint_id: UUID) -> PushEndpoint | None:
        model = await self._session.scalar(
            select(PushEndpointORM).where(PushEndpointORM.id == endpoint_id)
        )
        return endpoint_to_domain(model) if model is not None else None

    async def upsert(self, endpoint: PushEndpoint) -> None:
        await self._session.execute(
            insert(PushEndpointORM)
            .values(
                id=endpoint.id,
                user_id=endpoint.user_id,
                device_id=endpoint.device_id,
                provider=endpoint.provider,
                push_token=endpoint.push_token,
                active=endpoint.active,
                notifications_enabled=endpoint.notifications_enabled,
                last_registered_at=endpoint.last_registered_at,
                invalidated_at=endpoint.invalidated_at,
                created_at=endpoint.created_at,
                updated_at=endpoint.updated_at,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "device_id"],
                set_={
                    "push_token": endpoint.push_token,
                    "provider": endpoint.provider,
                    "active": endpoint.active,
                    "notifications_enabled": endpoint.notifications_enabled,
                    "last_registered_at": endpoint.last_registered_at,
                    "invalidated_at": endpoint.invalidated_at,
                    "updated_at": endpoint.updated_at,
                },
            )
        )

    async def invalidate_for_device(self, *, user_id: UUID, device_id: UUID) -> None:
        now = datetime.now(UTC)
        await self._session.execute(
            update(PushEndpointORM)
            .where(
                PushEndpointORM.user_id == user_id,
                PushEndpointORM.device_id == device_id,
            )
            .values(
                active=False,
                notifications_enabled=False,
                invalidated_at=now,
                updated_at=now,
            )
        )

    async def invalidate_for_user(self, *, user_id: UUID) -> None:
        now = datetime.now(UTC)
        await self._session.execute(
            update(PushEndpointORM)
            .where(PushEndpointORM.user_id == user_id)
            .values(
                active=False,
                notifications_enabled=False,
                invalidated_at=now,
                updated_at=now,
            )
        )
