from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from laoshiren.application.automations import write_ops as automation_write_ops
from laoshiren.application.automations.dto import (
    AttentionCandidateDTO,
    AutomationDTO,
    NotificationDTO,
)
from laoshiren.application.automations.materialize import materialize_due_automation
from laoshiren.application.automations.ports import (
    AutomationRunTrigger,
    AutomationUnitOfWork,
    NotificationPort,
)
from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.domain.automations.entities import (
    AttentionFeedbackAction,
    AttentionSubjectType,
    Automation,
    AutomationType,
    NotificationOutbox,
)
from laoshiren.domain.personal_state.exceptions import EntityNotFound

UnitOfWorkFactory = Callable[[], AutomationUnitOfWork]


def to_automation_dto(value: Automation, *, replayed: bool = False) -> AutomationDTO:
    return AutomationDTO(
        id=value.id,
        automation_type=value.automation_type,
        title=value.title,
        message=value.message,
        timezone_name=value.timezone_name,
        next_trigger_at=value.next_trigger_at,
        thing_id=value.thing_id,
        task_id=value.task_id,
        source_id=value.source_id,
        recurrence_interval_seconds=value.recurrence_interval_seconds,
        status=value.status,
        last_triggered_at=value.last_triggered_at,
        version=value.version,
        created_at=value.created_at,
        updated_at=value.updated_at,
        replayed=replayed,
    )


def to_notification_dto(value: NotificationOutbox) -> NotificationDTO:
    return NotificationDTO(
        id=value.id,
        automation_id=value.automation_id,
        title=value.title,
        message=value.message,
        thing_id=value.thing_id,
        status=value.status,
        attempt_count=value.attempt_count,
        submitted_at=value.submitted_at,
        error_code=value.error_code,
        next_attempt_at=value.next_attempt_at,
        created_at=value.created_at,
    )


class AutomationApplicationService:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        notification_port: NotificationPort,
        run_trigger: AutomationRunTrigger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._notification_port = notification_port
        self._run_trigger = run_trigger
        self._dispatch_owner = f"automation-dispatch-{uuid4()}"

    async def create(
        self,
        *,
        user_id: UUID,
        automation_type: AutomationType,
        title: str,
        message: str,
        timezone_name: str,
        next_trigger_at: datetime,
        idempotency_key: str,
        thing_id: UUID | None = None,
        task_id: UUID | None = None,
        source_id: UUID | None = None,
        recurrence_interval_seconds: int | None = None,
    ) -> AutomationDTO:
        if not title.strip() or not message.strip() or not timezone_name.strip():
            raise ValueError("Automation title, message and timezone must not be empty.")
        async with self._unit_of_work_factory() as unit_of_work:
            outcome = await automation_write_ops.apply_create_automation(
                cast(PersonalStateUnitOfWork, unit_of_work),
                user_id=user_id,
                automation_type=automation_type,
                title=title,
                message=message,
                timezone_name=timezone_name,
                next_trigger_at=next_trigger_at,
                idempotency_key=idempotency_key,
                thing_id=thing_id,
                task_id=task_id,
                source_id=source_id,
                recurrence_interval_seconds=recurrence_interval_seconds,
            )
            await unit_of_work.commit()
            automation = await unit_of_work.automations.get(
                user_id=user_id, automation_id=UUID(str(outcome.data["id"]))
            )
            if automation is None:
                raise RuntimeError("Automation creation did not persist.")
            return to_automation_dto(automation, replayed=outcome.replayed)

    async def get(self, *, user_id: UUID, automation_id: UUID) -> AutomationDTO:
        async with self._unit_of_work_factory() as unit_of_work:
            automation = await unit_of_work.automations.get(
                user_id=user_id, automation_id=automation_id
            )
            if automation is None:
                raise EntityNotFound("Automation was not found.")
            return to_automation_dto(automation)

    async def list_automations(self, *, user_id: UUID, limit: int = 50) -> list[AutomationDTO]:
        if not 1 <= limit <= 100:
            raise ValueError("Automation list limit must be between 1 and 100.")
        async with self._unit_of_work_factory() as unit_of_work:
            values = await unit_of_work.automations.list_for_user(user_id=user_id, limit=limit)
            return [to_automation_dto(value) for value in values]

    async def change_status(
        self,
        *,
        user_id: UUID,
        automation_id: UUID,
        action: str,
        expected_version: int,
        idempotency_key: str,
    ) -> AutomationDTO:
        async with self._unit_of_work_factory() as unit_of_work:
            outcome = await automation_write_ops.apply_change_automation_status(
                cast(PersonalStateUnitOfWork, unit_of_work),
                user_id=user_id,
                automation_id=automation_id,
                action=action,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            )
            await unit_of_work.commit()
            automation = await unit_of_work.automations.get(
                user_id=user_id, automation_id=UUID(str(outcome.data["id"]))
            )
            if automation is None:
                raise RuntimeError("Automation status change did not persist.")
            return to_automation_dto(automation, replayed=outcome.replayed)

    async def process_due(self, *, now: datetime | None = None, limit: int = 100) -> int:
        occurred_at = now or datetime.now(UTC)
        created_count = 0
        async with self._unit_of_work_factory() as unit_of_work:
            due = await unit_of_work.automations.list_due(now=occurred_at, limit=limit)
            for automation in due:
                occurrence = await materialize_due_automation(
                    unit_of_work,
                    automation=automation,
                    occurred_at=occurred_at,
                )
                if occurrence is not None:
                    created_count += 1
            await unit_of_work.commit()
        return created_count

    async def dispatch_pending(
        self,
        *,
        limit: int = 100,
        max_attempts: int = 3,
        lease_seconds: float = 60,
        retry_base_seconds: float = 30,
        retry_max_seconds: float = 900,
    ) -> int:
        submitted_count = 0
        for _ in range(limit):
            now = datetime.now(UTC)
            async with self._unit_of_work_factory() as unit_of_work:
                notification = await unit_of_work.notifications.claim_next(
                    owner=self._dispatch_owner,
                    now=now,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    max_attempts=max_attempts,
                )
                if notification is None:
                    await unit_of_work.rollback()
                    break
                await unit_of_work.commit()
            run_triggered = False
            if self._run_trigger is not None:
                try:
                    run_id = await self._run_trigger.trigger_from_notification(
                        notification=notification
                    )
                    run_triggered = run_id is not None
                except Exception:
                    run_triggered = False
            try:
                accepted = await self._notification_port.submit(
                    notification, idempotency_key=notification.occurrence_key
                )
            except Exception:
                error_code = "ADAPTER_EXCEPTION"
                accepted = False
            else:
                error_code = "ADAPTER_REJECTED"
            if accepted or run_triggered:
                notification.submitted()
            else:
                next_attempt = notification.attempt_count + 1
                delay = min(
                    retry_base_seconds * (2 ** max(next_attempt - 1, 0)),
                    retry_max_seconds,
                )
                notification.failed(
                    error_code,
                    retry_at=(
                        None
                        if next_attempt >= max_attempts
                        else datetime.now(UTC) + timedelta(seconds=delay)
                    ),
                )
            async with self._unit_of_work_factory() as unit_of_work:
                completed = await unit_of_work.notifications.complete(
                    notification=notification, owner=self._dispatch_owner
                )
                if completed:
                    await unit_of_work.commit()
                    submitted_count += int(accepted or run_triggered)
                else:
                    await unit_of_work.rollback()
        return submitted_count

    async def list_notifications(self, *, user_id: UUID, limit: int = 50) -> list[NotificationDTO]:
        async with self._unit_of_work_factory() as unit_of_work:
            values = await unit_of_work.notifications.list_for_user(user_id=user_id, limit=limit)
            return [to_notification_dto(value) for value in values]


class AttentionApplicationService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def get_candidates(
        self, *, user_id: UUID, now: datetime | None = None, limit: int = 10
    ) -> list[AttentionCandidateDTO]:
        current = now or datetime.now(UTC)
        async with self._unit_of_work_factory() as unit_of_work:
            values = await unit_of_work.attention.get_candidates(
                user_id=user_id, now=current, due_soon_hours=72, limit=limit
            )
            return [
                AttentionCandidateDTO(
                    subject_type=value.subject_type,
                    subject_id=value.subject_id,
                    thing_id=value.thing_id,
                    candidate_type=value.candidate_type,
                    severity=value.severity,
                    summary=value.summary,
                    due_at=value.due_at,
                    last_surfaced_at=value.last_surfaced_at,
                    next_eligible_at=value.next_eligible_at,
                    acknowledged=value.acknowledged,
                )
                for value in values
            ]

    async def record_feedback(
        self,
        *,
        user_id: UUID,
        subject_type: AttentionSubjectType,
        subject_id: UUID,
        action: AttentionFeedbackAction,
        dismissed_until: datetime | None,
    ) -> None:
        if action is AttentionFeedbackAction.DISMISSED and dismissed_until is None:
            raise ValueError("Dismissed feedback requires dismissed_until.")
        async with self._unit_of_work_factory() as unit_of_work:
            if subject_type in {
                AttentionSubjectType.THING,
                AttentionSubjectType.DEADLINE,
            }:
                subject_exists = (
                    await unit_of_work.things.get(user_id=user_id, thing_id=subject_id) is not None
                )
            elif subject_type is AttentionSubjectType.TASK:
                subject_exists = (
                    await unit_of_work.tasks.get(user_id=user_id, task_id=subject_id) is not None
                )
            else:
                subject_exists = (
                    await unit_of_work.blockers.get(user_id=user_id, blocker_id=subject_id)
                    is not None
                )
            if not subject_exists:
                raise EntityNotFound("Attention subject was not found.")
            await unit_of_work.attention.record_feedback(
                user_id=user_id,
                subject_type=subject_type,
                subject_id=subject_id,
                action=action,
                now=datetime.now(UTC),
                dismissed_until=dismissed_until,
            )
            await unit_of_work.commit()
