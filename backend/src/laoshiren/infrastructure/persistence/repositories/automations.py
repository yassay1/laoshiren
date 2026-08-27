from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from laoshiren.domain.automations.entities import (
    AttentionCandidate,
    AttentionFeedbackAction,
    AttentionSubjectType,
    Automation,
    AutomationStatus,
    NotificationOutbox,
    NotificationStatus,
)
from laoshiren.domain.personal_state.value_objects import (
    BlockerStatus,
    ThingStatus,
)
from laoshiren.infrastructure.persistence.orm.personal_state import (
    AttentionFeedbackORM,
    AutomationOperationORM,
    AutomationORM,
    BlockerORM,
    NotificationOutboxORM,
    ThingORM,
)

ATTENTION_SURFACE_COOLDOWN = timedelta(hours=4)


def automation_to_domain(model: AutomationORM) -> Automation:
    return Automation(
        id=model.id,
        user_id=model.user_id,
        automation_type=model.automation_type,
        title=model.title,
        message=model.message,
        timezone_name=model.timezone_name,
        next_trigger_at=model.next_trigger_at,
        idempotency_key=model.idempotency_key,
        thing_id=model.thing_id,
        task_id=model.task_id,
        source_id=model.source_id,
        recurrence_interval_seconds=model.recurrence_interval_seconds,
        status=model.status,
        last_triggered_at=model.last_triggered_at,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def notification_to_domain(model: NotificationOutboxORM) -> NotificationOutbox:
    return NotificationOutbox(
        id=model.id,
        user_id=model.user_id,
        automation_id=model.automation_id,
        occurrence_key=model.occurrence_key,
        title=model.title,
        message=model.message,
        thing_id=model.thing_id,
        status=model.status,
        attempt_count=model.attempt_count,
        submitted_at=model.submitted_at,
        error_code=model.error_code,
        claim_owner=model.claim_owner,
        lease_expires_at=model.lease_expires_at,
        next_attempt_at=model.next_attempt_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlAlchemyAutomationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, automation: Automation) -> None:
        self._session.add(
            AutomationORM(
                id=automation.id,
                user_id=automation.user_id,
                automation_type=automation.automation_type,
                title=automation.title,
                message=automation.message,
                timezone_name=automation.timezone_name,
                next_trigger_at=automation.next_trigger_at,
                thing_id=automation.thing_id,
                task_id=automation.task_id,
                source_id=automation.source_id,
                recurrence_interval_seconds=automation.recurrence_interval_seconds,
                status=automation.status,
                last_triggered_at=automation.last_triggered_at,
                version=automation.version,
                idempotency_key=automation.idempotency_key,
                created_at=automation.created_at,
                updated_at=automation.updated_at,
            )
        )

    async def get(self, *, user_id: UUID, automation_id: UUID) -> Automation | None:
        model = await self._session.scalar(
            select(AutomationORM).where(
                AutomationORM.id == automation_id, AutomationORM.user_id == user_id
            )
        )
        return automation_to_domain(model) if model is not None else None

    async def get_by_idempotency(self, *, user_id: UUID, key: str) -> Automation | None:
        model = await self._session.scalar(
            select(AutomationORM).where(
                AutomationORM.user_id == user_id, AutomationORM.idempotency_key == key
            )
        )
        return automation_to_domain(model) if model is not None else None

    async def list_for_user(self, *, user_id: UUID, limit: int) -> list[Automation]:
        models = (
            await self._session.scalars(
                select(AutomationORM)
                .where(AutomationORM.user_id == user_id)
                .order_by(AutomationORM.created_at.desc(), AutomationORM.id.desc())
                .limit(limit)
            )
        ).all()
        return [automation_to_domain(model) for model in models]

    async def list_due(self, *, now: datetime, limit: int) -> list[Automation]:
        models = (
            await self._session.scalars(
                select(AutomationORM)
                .where(
                    AutomationORM.status == AutomationStatus.ACTIVE,
                    AutomationORM.next_trigger_at <= now,
                )
                .order_by(AutomationORM.next_trigger_at, AutomationORM.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        return [automation_to_domain(model) for model in models]

    async def update(self, automation: Automation, *, expected_version: int) -> bool:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(AutomationORM)
                .where(
                    AutomationORM.id == automation.id,
                    AutomationORM.version == expected_version,
                )
                .values(
                    status=automation.status,
                    next_trigger_at=automation.next_trigger_at,
                    last_triggered_at=automation.last_triggered_at,
                    version=automation.version,
                    updated_at=automation.updated_at,
                )
            ),
        )
        return result.rowcount == 1

    async def get_operation(
        self, *, user_id: UUID, key: str
    ) -> tuple[UUID, int] | None:
        row = (
            await self._session.execute(
                select(
                    AutomationOperationORM.automation_id,
                    AutomationOperationORM.target_version,
                ).where(
                    AutomationOperationORM.user_id == user_id,
                    AutomationOperationORM.idempotency_key == key,
                )
            )
        ).one_or_none()
        return (row[0], row[1]) if row is not None else None

    async def record_operation(
        self, *, user_id: UUID, automation_id: UUID, key: str, target_version: int
    ) -> None:
        self._session.add(
            AutomationOperationORM(
                user_id=user_id,
                automation_id=automation_id,
                idempotency_key=key,
                target_version=target_version,
            )
        )


class SqlAlchemyNotificationOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, notification: NotificationOutbox) -> bool:
        statement = (
            insert(NotificationOutboxORM)
            .values(
                id=notification.id,
                user_id=notification.user_id,
                automation_id=notification.automation_id,
                occurrence_key=notification.occurrence_key,
                title=notification.title,
                message=notification.message,
                thing_id=notification.thing_id,
                status=notification.status,
                attempt_count=notification.attempt_count,
                created_at=notification.created_at,
                updated_at=notification.updated_at,
                claim_owner=notification.claim_owner,
                lease_expires_at=notification.lease_expires_at,
                next_attempt_at=notification.next_attempt_at,
            )
            .on_conflict_do_nothing(index_elements=["occurrence_key"])
            .returning(NotificationOutboxORM.id)
        )
        return (await self._session.scalar(statement)) is not None

    async def claim_next(
        self,
        *,
        owner: str,
        now: datetime,
        lease_expires_at: datetime,
        max_attempts: int,
    ) -> NotificationOutbox | None:
        candidate = (
            select(NotificationOutboxORM.id)
            .where(
                NotificationOutboxORM.attempt_count < max_attempts,
                (
                    (
                        (NotificationOutboxORM.status == NotificationStatus.PENDING)
                        & (
                            NotificationOutboxORM.lease_expires_at.is_(None)
                            | (NotificationOutboxORM.lease_expires_at <= now)
                        )
                    )
                    | (
                        (NotificationOutboxORM.status == NotificationStatus.FAILED)
                        & (NotificationOutboxORM.next_attempt_at.is_not(None))
                        & (NotificationOutboxORM.next_attempt_at <= now)
                    )
                ),
            )
            .order_by(NotificationOutboxORM.created_at, NotificationOutboxORM.id)
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        model = await self._session.scalar(
            update(NotificationOutboxORM)
            .where(NotificationOutboxORM.id == candidate)
            .values(
                status=NotificationStatus.PENDING,
                claim_owner=owner,
                lease_expires_at=lease_expires_at,
                next_attempt_at=None,
            )
            .returning(NotificationOutboxORM)
        )
        return notification_to_domain(model) if model is not None else None

    async def complete(self, *, notification: NotificationOutbox, owner: str) -> bool:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(NotificationOutboxORM)
                .where(
                    NotificationOutboxORM.id == notification.id,
                    NotificationOutboxORM.claim_owner == owner,
                )
            .values(
                status=notification.status,
                attempt_count=notification.attempt_count,
                submitted_at=notification.submitted_at,
                error_code=notification.error_code,
                updated_at=notification.updated_at,
                claim_owner=notification.claim_owner,
                lease_expires_at=notification.lease_expires_at,
                next_attempt_at=notification.next_attempt_at,
            )
            ),
        )
        return result.rowcount == 1

    async def list_for_user(
        self, *, user_id: UUID, limit: int
    ) -> list[NotificationOutbox]:
        models = (
            await self._session.scalars(
                select(NotificationOutboxORM)
                .where(NotificationOutboxORM.user_id == user_id)
                .order_by(NotificationOutboxORM.created_at.desc(), NotificationOutboxORM.id.desc())
                .limit(limit)
            )
        ).all()
        return [notification_to_domain(model) for model in models]


class SqlAlchemyAttentionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_candidates(
        self, *, user_id: UUID, now: datetime, due_soon_hours: int, limit: int
    ) -> list[AttentionCandidate]:
        feedback_models = (
            await self._session.scalars(
                select(AttentionFeedbackORM).where(AttentionFeedbackORM.user_id == user_id)
            )
        ).all()
        feedback = {
            (item.subject_type, item.subject_id): item for item in feedback_models
        }
        candidates: list[AttentionCandidate] = []
        things = (
            await self._session.scalars(
                select(ThingORM).where(
                    ThingORM.user_id == user_id,
                    ThingORM.deadline_at.is_not(None),
                    ThingORM.deadline_at <= now + timedelta(hours=due_soon_hours),
                    ThingORM.status.not_in(
                        [ThingStatus.COMPLETED, ThingStatus.CANCELLED, ThingStatus.ARCHIVED]
                    ),
                )
            )
        ).all()
        for thing in things:
            item = feedback.get((AttentionSubjectType.DEADLINE, thing.id))
            if item and (
                item.acknowledged_at
                or (item.dismissed_until and item.dismissed_until > now)
                or (
                    item.last_surfaced_at
                    and now - item.last_surfaced_at < ATTENTION_SURFACE_COOLDOWN
                )
            ):
                continue
            assert thing.deadline_at is not None
            if thing.deadline_at < now:
                candidate_type, severity = "overdue", "high"
            elif thing.deadline_at.date() == now.date():
                candidate_type, severity = "due_today", "high"
            else:
                candidate_type, severity = "due_soon", "medium"
            candidates.append(
                AttentionCandidate(
                    subject_type=AttentionSubjectType.DEADLINE,
                    subject_id=thing.id,
                    thing_id=thing.id,
                    candidate_type=candidate_type,
                    severity=severity,
                    summary=f"{thing.name}：{candidate_type}",
                    due_at=thing.deadline_at,
                    last_surfaced_at=item.last_surfaced_at if item else None,
                    next_eligible_at=item.dismissed_until if item else None,
                    acknowledged=bool(item and item.acknowledged_at),
                )
            )
        blockers = (
            await self._session.scalars(
                select(BlockerORM)
                .join(ThingORM, ThingORM.id == BlockerORM.thing_id)
                .where(ThingORM.user_id == user_id, BlockerORM.status == BlockerStatus.OPEN)
            )
        ).all()
        for blocker in blockers:
            item = feedback.get((AttentionSubjectType.BLOCKER, blocker.id))
            if item and (
                item.acknowledged_at
                or (item.dismissed_until and item.dismissed_until > now)
                or (
                    item.last_surfaced_at
                    and now - item.last_surfaced_at < ATTENTION_SURFACE_COOLDOWN
                )
            ):
                continue
            too_long = blocker.blocked_since <= now - timedelta(hours=24)
            candidates.append(
                AttentionCandidate(
                    subject_type=AttentionSubjectType.BLOCKER,
                    subject_id=blocker.id,
                    thing_id=blocker.thing_id,
                    candidate_type="blocked_too_long" if too_long else "blocked",
                    severity="high" if too_long else "medium",
                    summary=blocker.description,
                    due_at=None,
                    last_surfaced_at=item.last_surfaced_at if item else None,
                    next_eligible_at=item.dismissed_until if item else None,
                    acknowledged=bool(item and item.acknowledged_at),
                )
            )
        candidates.sort(
            key=lambda item: (
                0 if item.severity == "high" else 1,
                item.due_at or now,
                str(item.subject_id),
            )
        )
        return candidates[:limit]

    async def record_feedback(
        self,
        *,
        user_id: UUID,
        subject_type: AttentionSubjectType,
        subject_id: UUID,
        action: AttentionFeedbackAction,
        now: datetime,
        dismissed_until: datetime | None,
    ) -> None:
        values: dict[str, object] = {"updated_at": now}
        if action is AttentionFeedbackAction.SURFACED:
            values.update(last_surfaced_at=now)
        elif action is AttentionFeedbackAction.ACKNOWLEDGED:
            values.update(acknowledged_at=now)
        else:
            values.update(dismissed_until=dismissed_until)
        insert_values = {
            "user_id": user_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "surface_count": 1 if action is AttentionFeedbackAction.SURFACED else 0,
            **values,
        }
        update_values = dict(values)
        if action is AttentionFeedbackAction.SURFACED:
            update_values["surface_count"] = AttentionFeedbackORM.surface_count + 1
        await self._session.execute(
            insert(AttentionFeedbackORM)
            .values(**insert_values)
            .on_conflict_do_update(
                index_elements=["user_id", "subject_type", "subject_id"],
                set_=update_values,
            )
        )
