from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from laoshiren.domain.personal_state.value_objects import (
    BlockerSeverity,
    BlockerStatus,
    DateCertainty,
    DatePrecision,
    TaskStatus,
    ThingRelationType,
    ThingStatus,
)


@dataclass(frozen=True, slots=True)
class ThingDTO:
    id: UUID
    user_id: UUID
    name: str
    status: ThingStatus
    current_stage: str | None
    deadline_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TaskDTO:
    id: UUID
    thing_id: UUID
    title: str
    status: TaskStatus
    version: int
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MutationResultDTO:
    mutation_id: UUID
    target_id: UUID
    target_version: int
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ThingDateDTO:
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


@dataclass(frozen=True, slots=True)
class TimelineEventDTO:
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


@dataclass(frozen=True, slots=True)
class BlockerDTO:
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


@dataclass(frozen=True, slots=True)
class ThingRelationDTO:
    from_thing_id: UUID
    to_thing_id: UUID
    relation_type: ThingRelationType
    note: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StateMutationDTO:
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


@dataclass(frozen=True, slots=True)
class UpcomingThingDTO:
    thing_id: UUID
    name: str
    deadline_at: datetime
    open_task_count: int


@dataclass(frozen=True, slots=True)
class BlockedThingDTO:
    thing_id: UUID
    thing_name: str
    description: str
    severity: BlockerSeverity


@dataclass(frozen=True, slots=True)
class ActiveThingDTO:
    thing_id: UUID
    name: str
    current_stage: str | None
    open_task_count: int


@dataclass(frozen=True, slots=True)
class RecentThingDTO:
    thing_id: UUID
    name: str
    status: ThingStatus
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StateOverviewDTO:
    upcoming: tuple[UpcomingThingDTO, ...]
    blocked: tuple[BlockedThingDTO, ...]
    active: tuple[ActiveThingDTO, ...]
    recent: tuple[RecentThingDTO, ...]
