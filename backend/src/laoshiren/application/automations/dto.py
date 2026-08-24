from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from laoshiren.domain.automations.entities import (
    AttentionSubjectType,
    AutomationStatus,
    AutomationType,
    NotificationStatus,
)


@dataclass(frozen=True, slots=True)
class AutomationDTO:
    id: UUID
    automation_type: AutomationType
    title: str
    message: str
    timezone_name: str
    next_trigger_at: datetime
    thing_id: UUID | None
    task_id: UUID | None
    source_id: UUID | None
    recurrence_interval_seconds: int | None
    status: AutomationStatus
    last_triggered_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class NotificationDTO:
    id: UUID
    automation_id: UUID
    title: str
    message: str
    thing_id: UUID | None
    status: NotificationStatus
    attempt_count: int
    submitted_at: datetime | None
    error_code: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AttentionCandidateDTO:
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
