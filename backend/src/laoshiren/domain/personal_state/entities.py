from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from laoshiren.domain.personal_state.exceptions import InvalidStateTransition
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


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class Thing:
    user_id: UUID
    name: str
    id: UUID = field(default_factory=uuid4)
    status: ThingStatus = ThingStatus.ACTIVE
    current_stage: str | None = None
    deadline_at: datetime | None = None
    archived_at: datetime | None = None
    deleted_at: datetime | None = None
    merged_into_thing_id: UUID | None = None
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def touch(self) -> None:
        self.updated_at = utc_now()
        self.version += 1

    def set_primary_deadline(self, value: datetime) -> None:
        if value.tzinfo is None:
            raise ValueError("Deadline must include timezone information.")
        self.deadline_at = value
        self.touch()

    def revise(
        self,
        *,
        name: str | None = None,
        status: ThingStatus | None = None,
        current_stage: str | None = None,
        update_current_stage: bool = False,
    ) -> None:
        if name is not None:
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("Thing name must not be empty.")
            self.name = normalized_name
        if status is not None:
            self.status = status
        if update_current_stage:
            self.current_stage = current_stage.strip() if current_stage else None
        self.touch()

    def archive(self) -> None:
        if self.archived_at is not None:
            return
        self.archived_at = utc_now()
        self.updated_at = self.archived_at
        self.version += 1

    def unarchive(self) -> None:
        if self.archived_at is None:
            return
        self.archived_at = None
        self.updated_at = utc_now()
        self.version += 1

    def merge_into(self, *, canonical_thing_id: UUID) -> None:
        if canonical_thing_id == self.id:
            raise ValueError("A Thing cannot merge into itself.")
        if self.merged_into_thing_id is not None:
            raise InvalidStateTransition("A merged Thing cannot be merged again.")
        self.merged_into_thing_id = canonical_thing_id
        self.updated_at = utc_now()
        self.version += 1

    def delete(self) -> None:
        if self.deleted_at is not None:
            return
        if self.merged_into_thing_id is not None:
            raise InvalidStateTransition("A merged Thing cannot be deleted directly.")
        self.deleted_at = utc_now()
        self.updated_at = self.deleted_at
        self.version += 1


@dataclass(slots=True)
class Task:
    user_id: UUID
    title: str
    thing_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    status: TaskStatus = TaskStatus.TODO
    version: int = 1
    completed_at: datetime | None = None
    due_at: datetime | None = None
    recurrence_interval_days: int | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def complete(self, *, occurred_at: datetime | None = None) -> None:
        if self.status is TaskStatus.CANCELLED:
            raise InvalidStateTransition("A cancelled task cannot be completed directly.")
        if self.status is TaskStatus.DONE:
            return
        completed_at = occurred_at or utc_now()
        if self.recurrence_interval_days is not None:
            if self.recurrence_interval_days <= 0 or self.due_at is None:
                raise ValueError("Recurring Task requires a due time and a positive interval.")
            self.status = TaskStatus.TODO
            self.completed_at = completed_at
            self.due_at = self.due_at + timedelta(days=self.recurrence_interval_days)
            self.updated_at = completed_at
            self.version += 1
            return
        self.status = TaskStatus.DONE
        self.completed_at = completed_at
        self.updated_at = completed_at
        self.version += 1

    def reopen(self) -> None:
        if self.status not in {TaskStatus.DONE, TaskStatus.CANCELLED}:
            raise InvalidStateTransition("Only a terminal task can be reopened.")
        self.status = TaskStatus.TODO
        self.completed_at = None
        self.updated_at = utc_now()
        self.version += 1

    def transition_to(self, target: TaskStatus) -> None:
        if target is self.status:
            return
        if self.status in {TaskStatus.DONE, TaskStatus.CANCELLED}:
            if target is TaskStatus.TODO:
                self.reopen()
                return
            raise InvalidStateTransition("A terminal task must be reopened before transition.")
        if target is TaskStatus.DONE:
            self.complete()
            return
        if target is TaskStatus.CANCELLED:
            self.status = target
            self.completed_at = None
            self.updated_at = utc_now()
            self.version += 1
            return
        raise InvalidStateTransition("Task transition target is not supported.")


@dataclass(slots=True)
class ThingDate:
    thing_id: UUID
    kind: ThingDateType
    value: datetime
    timezone_name: str
    precision: DatePrecision
    certainty: DateCertainty
    label: str | None = None
    id: UUID = field(default_factory=uuid4)
    is_primary: bool = False
    source_id: UUID | None = None
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def revise(
        self,
        *,
        value: datetime,
        timezone_name: str,
        precision: DatePrecision,
        certainty: DateCertainty,
        is_primary: bool,
    ) -> None:
        if value.tzinfo is None:
            raise ValueError("Date must include timezone information.")
        if not timezone_name.strip():
            raise ValueError("Date timezone must not be empty.")
        if is_primary and certainty is not DateCertainty.CONFIRMED:
            raise ValueError("Only a confirmed date can become primary.")
        self.value = value
        self.timezone_name = timezone_name.strip()
        self.precision = precision
        self.certainty = certainty
        self.is_primary = is_primary
        self.updated_at = utc_now()
        self.version += 1


@dataclass(slots=True)
class ThingContextEntry:
    thing_id: UUID
    label: str
    content: str
    id: UUID = field(default_factory=uuid4)
    source_id: UUID | None = None
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def revise(self, *, label: str, content: str) -> None:
        normalized_label = label.strip()
        normalized_content = content.strip()
        if not normalized_label or not normalized_content:
            raise ValueError("Thing context label and content must not be empty.")
        self.label = normalized_label
        self.content = normalized_content
        self.updated_at = utc_now()
        self.version += 1


@dataclass(slots=True)
class Blocker:
    thing_id: UUID
    description: str
    severity: BlockerSeverity
    id: UUID = field(default_factory=uuid4)
    task_id: UUID | None = None
    status: BlockerStatus = BlockerStatus.OPEN
    blocked_since: datetime = field(default_factory=utc_now)
    resolved_at: datetime | None = None
    source_id: UUID | None = None
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def resolve(self) -> None:
        if self.status is not BlockerStatus.OPEN:
            raise InvalidStateTransition("Only an open blocker can be resolved.")
        self.status = BlockerStatus.RESOLVED
        self.resolved_at = utc_now()
        self.updated_at = self.resolved_at
        self.version += 1


@dataclass(slots=True)
class ThingRelation:
    from_thing_id: UUID
    to_thing_id: UUID
    relation_type: ThingRelationType
    note: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.from_thing_id == self.to_thing_id:
            raise ValueError("A Thing cannot relate to itself.")


@dataclass(slots=True)
class StateMutation:
    user_id: UUID
    thing_id: UUID | None
    action_id: str
    mutation_type: str
    target_type: str
    target_id: UUID
    after: dict[str, object]
    reason: str
    idempotency_key: str
    id: UUID = field(default_factory=uuid4)
    run_id: UUID | None = None
    before: dict[str, object] | None = None
    source_id: UUID | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class TimelineEvent:
    user_id: UUID
    thing_id: UUID
    event_type: str
    title: str
    occurred_at: datetime
    id: UUID = field(default_factory=uuid4)
    summary: str | None = None
    source_id: UUID | None = None
    mutation_id: UUID | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
