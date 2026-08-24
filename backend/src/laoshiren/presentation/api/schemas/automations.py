from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from laoshiren.application.automations.dto import (
    AttentionCandidateDTO,
    AutomationDTO,
    NotificationDTO,
)
from laoshiren.domain.automations.entities import (
    AttentionFeedbackAction,
    AttentionSubjectType,
    AutomationStatus,
    AutomationType,
    NotificationStatus,
)


class CreateAutomationRequest(BaseModel):
    automation_type: AutomationType
    title: str = Field(min_length=1, max_length=300)
    message: str = Field(min_length=1, max_length=2000)
    timezone: str = Field(min_length=1, max_length=100)
    next_trigger_at: datetime
    thing_id: UUID | None = None
    task_id: UUID | None = None
    source_id: UUID | None = None
    recurrence_interval_seconds: int | None = Field(default=None, ge=60)


class ChangeAutomationRequest(BaseModel):
    action: Literal["PAUSE", "RESUME", "CANCEL"]
    expected_version: int = Field(ge=1)


class AutomationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    replayed: bool

    @classmethod
    def from_dto(cls, value: AutomationDTO) -> "AutomationResponse":
        return cls.model_validate(value)


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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

    @classmethod
    def from_dto(cls, value: NotificationDTO) -> "NotificationResponse":
        return cls.model_validate(value)


class AttentionCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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

    @classmethod
    def from_dto(cls, value: AttentionCandidateDTO) -> "AttentionCandidateResponse":
        return cls.model_validate(value)


class AttentionResponse(BaseModel):
    items: list[AttentionCandidateResponse]


class AttentionFeedbackRequest(BaseModel):
    action: AttentionFeedbackAction
    dismissed_until: datetime | None = None
