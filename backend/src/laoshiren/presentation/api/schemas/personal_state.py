from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from laoshiren.application.personal_state.dto import (
    BlockerDTO,
    StateMutationDTO,
    TaskDTO,
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
    ThingRelationType,
    ThingStatus,
)


class CreateThingRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


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
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dto(cls, value: ThingDTO) -> "ThingResponse":
        return cls.model_validate(value)


class CreateTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class SetDeadlineRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=50)
    value: datetime
    timezone: str = Field(min_length=1, max_length=100)
    precision: DatePrecision
    certainty: DateCertainty
    is_primary: bool = True
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class ThingDateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    thing_id: UUID
    kind: str
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
    thing_id: UUID
    title: str
    status: TaskStatus
    version: int
    completed_at: datetime | None
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
