from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from laoshiren.application.personal_state.dto import (
    BlockerDTO,
    StateMutationDTO,
    TaskDTO,
    ThingContextEntryDTO,
    ThingDateDTO,
    ThingDTO,
    ThingRelationDTO,
    TimelineEventDTO,
)
from laoshiren.domain.personal_state.value_objects import (
    BlockerSeverity,
    BlockerStatus,
    DateCertainty,
    DatePrecision,
    TaskStatus,
    ThingDateType,
    ThingRelationType,
    ThingStatus,
)


class CreateThingRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class MergeThingsRequest(BaseModel):
    duplicate_thing_id: UUID
    expected_canonical_version: int = Field(ge=1)
    expected_duplicate_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class UpdateThingRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: ThingStatus | None = None
    current_stage: str | None = Field(default=None, max_length=200)
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class ThingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    name: str
    status: ThingStatus
    current_stage: str | None
    deadline_at: datetime | None
    merged_into_thing_id: UUID | None
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dto(cls, value: ThingDTO) -> "ThingResponse":
        return cls.model_validate(value)


class CreateTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    due_at: datetime | None = None
    recurrence_interval_days: int | None = Field(default=None, ge=1)


class SetDeadlineRequest(BaseModel):
    kind: ThingDateType
    label: str | None = Field(default=None, max_length=200)
    value: datetime
    timezone: str = Field(min_length=1, max_length=100)
    precision: DatePrecision
    certainty: DateCertainty
    is_primary: bool = True
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)
    source_id: UUID | None = None


class ThingDateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    thing_id: UUID
    kind: ThingDateType
    label: str | None
    value: datetime
    timezone_name: str
    precision: DatePrecision
    certainty: DateCertainty
    is_primary: bool
    source_id: UUID | None
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dto(cls, value: ThingDateDTO) -> "ThingDateResponse":
        return cls.model_validate(value)


class SetThingContextRequest(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=10000)
    entry_id: UUID | None = None
    expected_version: int | None = Field(default=None, ge=1)
    source_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=500)


class ThingContextEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    thing_id: UUID
    label: str
    content: str
    source_id: UUID | None
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dto(cls, value: ThingContextEntryDTO) -> "ThingContextEntryResponse":
        return cls.model_validate(value)


class TimelineEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    thing_id: UUID
    event_type: str
    title: str
    summary: str | None
    occurred_at: datetime
    source_id: UUID | None
    mutation_id: UUID | None
    metadata: dict[str, object]
    created_at: datetime

    @classmethod
    def from_dto(cls, value: TimelineEventDTO) -> "TimelineEventResponse":
        return cls.model_validate(value)


class UpdateTaskRequest(BaseModel):
    status: TaskStatus
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    thing_id: UUID | None
    title: str
    status: TaskStatus
    version: int
    completed_at: datetime | None
    due_at: datetime | None
    recurrence_interval_days: int | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dto(cls, value: TaskDTO) -> "TaskResponse":
        return cls.model_validate(value)


class MutationResponse(BaseModel):
    mutation_id: UUID
    target_id: UUID
    target_version: int
    replayed: bool


class UpdateDateRequest(BaseModel):
    value: datetime
    timezone: str = Field(min_length=1, max_length=100)
    precision: DatePrecision
    certainty: DateCertainty
    is_primary: bool
    expected_version: int = Field(ge=1)
    expected_thing_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class CreateBlockerRequest(BaseModel):
    description: str = Field(min_length=1, max_length=1000)
    severity: BlockerSeverity
    task_id: UUID | None = None
    source_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=500)


class ResolveBlockerRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class BlockerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    thing_id: UUID
    task_id: UUID | None
    description: str
    severity: BlockerSeverity
    status: BlockerStatus
    blocked_since: datetime
    resolved_at: datetime | None
    source_id: UUID | None
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dto(cls, value: BlockerDTO) -> "BlockerResponse":
        return cls.model_validate(value)


class CreateThingRelationRequest(BaseModel):
    to_thing_id: UUID
    relation_type: ThingRelationType
    note: str | None = Field(default=None, max_length=1000)
    reason: str = Field(min_length=1, max_length=500)


class ThingRelationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_thing_id: UUID
    to_thing_id: UUID
    relation_type: ThingRelationType
    note: str | None
    created_at: datetime

    @classmethod
    def from_dto(cls, value: ThingRelationDTO) -> "ThingRelationResponse":
        return cls.model_validate(value)


class ThingRelationCreatedResponse(BaseModel):
    created: bool


class StateMutationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    thing_id: UUID
    action_id: str
    mutation_type: str
    target_type: str
    target_id: UUID
    before: dict[str, object] | None
    after: dict[str, object]
    reason: str
    source_id: UUID | None
    created_at: datetime

    @classmethod
    def from_dto(cls, value: StateMutationDTO) -> "StateMutationResponse":
        return cls.model_validate(value)
