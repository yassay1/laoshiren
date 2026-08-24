from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4


def utc_now() -> datetime:
    return datetime.now(UTC)


class AutomationType(StrEnum):
    ONE_SHOT = "ONE_SHOT"
    RECURRING = "RECURRING"
    CONDITION_WATCH = "CONDITION_WATCH"


class AutomationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class NotificationStatus(StrEnum):
    PENDING = "PENDING"
    SUBMITTED_TO_ADAPTER = "SUBMITTED_TO_ADAPTER"
    FAILED = "FAILED"


class AttentionSubjectType(StrEnum):
    THING = "THING"
    TASK = "TASK"
    DEADLINE = "DEADLINE"
    BLOCKER = "BLOCKER"


class AttentionFeedbackAction(StrEnum):
    SURFACED = "SURFACED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISMISSED = "DISMISSED"


@dataclass(slots=True)
class Automation:
    user_id: UUID
    automation_type: AutomationType
    title: str
    message: str
    timezone_name: str
    next_trigger_at: datetime
    idempotency_key: str
    id: UUID = field(default_factory=uuid4)
    thing_id: UUID | None = None
    task_id: UUID | None = None
    source_id: UUID | None = None
    recurrence_interval_seconds: int | None = None
    status: AutomationStatus = AutomationStatus.ACTIVE
    last_triggered_at: datetime | None = None
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.next_trigger_at.tzinfo is None:
            raise ValueError("Automation trigger must include timezone information.")
        if self.automation_type is AutomationType.RECURRING:
            if self.recurrence_interval_seconds is None or self.recurrence_interval_seconds < 60:
                raise ValueError("Recurring Automation interval must be at least 60 seconds.")
        elif self.recurrence_interval_seconds is not None:
            raise ValueError("Only a recurring Automation can define an interval.")

    def cancel(self) -> None:
        if self.status in {AutomationStatus.COMPLETED, AutomationStatus.CANCELLED}:
            return
        self.status = AutomationStatus.CANCELLED
        self.updated_at = utc_now()
        self.version += 1

    def pause(self) -> None:
        if self.status is not AutomationStatus.ACTIVE:
            raise ValueError("Only an active Automation can be paused.")
        self.status = AutomationStatus.PAUSED
        self.updated_at = utc_now()
        self.version += 1

    def resume(self) -> None:
        if self.status is not AutomationStatus.PAUSED:
            raise ValueError("Only a paused Automation can be resumed.")
        self.status = AutomationStatus.ACTIVE
        self.updated_at = utc_now()
        self.version += 1

    def mark_triggered(self, occurred_at: datetime) -> None:
        self.last_triggered_at = occurred_at
        if self.automation_type is AutomationType.ONE_SHOT:
            self.status = AutomationStatus.COMPLETED
        elif self.automation_type is AutomationType.RECURRING:
            assert self.recurrence_interval_seconds is not None
            self.next_trigger_at = occurred_at + timedelta(
                seconds=self.recurrence_interval_seconds
            )
        self.updated_at = occurred_at
        self.version += 1


@dataclass(slots=True)
class NotificationOutbox:
    user_id: UUID
    automation_id: UUID
    occurrence_key: str
    title: str
    message: str
    id: UUID = field(default_factory=uuid4)
    thing_id: UUID | None = None
    status: NotificationStatus = NotificationStatus.PENDING
    attempt_count: int = 0
    submitted_at: datetime | None = None
    error_code: str | None = None
    claim_owner: str | None = None
    lease_expires_at: datetime | None = None
    next_attempt_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def submitted(self) -> None:
        self.status = NotificationStatus.SUBMITTED_TO_ADAPTER
        self.attempt_count += 1
        self.submitted_at = utc_now()
        self.updated_at = self.submitted_at
        self.claim_owner = None
        self.lease_expires_at = None
        self.next_attempt_at = None

    def failed(self, error_code: str, *, retry_at: datetime | None = None) -> None:
        self.status = NotificationStatus.FAILED
        self.attempt_count += 1
        self.error_code = error_code
        self.updated_at = utc_now()
        self.claim_owner = None
        self.lease_expires_at = None
        self.next_attempt_at = retry_at


@dataclass(frozen=True, slots=True)
class AttentionCandidate:
    subject_type: AttentionSubjectType
    subject_id: UUID
    thing_id: UUID
    candidate_type: str
    severity: str
    summary: str
    due_at: datetime | None
    last_surfaced_at: datetime | None
    next_eligible_at: datetime | None
    acknowledged: bool
