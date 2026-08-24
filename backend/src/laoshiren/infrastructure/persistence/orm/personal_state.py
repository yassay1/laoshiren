from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from laoshiren.domain.automations.entities import (
    AttentionSubjectType,
    AutomationStatus,
    AutomationType,
    NotificationStatus,
)
from laoshiren.domain.memories.entities import MemoryStatus, MemoryType
from laoshiren.domain.personal_state.value_objects import (
    BlockerSeverity,
    BlockerStatus,
    DateCertainty,
    DatePrecision,
    TaskStatus,
    ThingRelationType,
    ThingStatus,
)
from laoshiren.domain.runtime.entities import (
    MessageRole,
    RunEventType,
    RunStatus,
    RunTrigger,
    ToolExecutionStatus,
)
from laoshiren.domain.sources.entities import (
    ProcessingStatus,
    SourceOrigin,
    SourceRelationType,
    SourceType,
)
from laoshiren.infrastructure.persistence.orm.base import Base


class UserORM(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ThingORM(Base):
    __tablename__ = "things"
    __table_args__ = (Index("ix_things_user_updated", "user_id", "updated_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[ThingStatus] = mapped_column(Enum(ThingStatus, name="thing_status"))
    current_stage: Mapped[str | None] = mapped_column(String(200))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskORM(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_thing_status", "thing_id", "status"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    thing_id: Mapped[UUID] = mapped_column(ForeignKey("things.id"))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus, name="task_status"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ThingDateORM(Base):
    __tablename__ = "thing_dates"
    __table_args__ = (
        Index("ix_thing_dates_thing_kind", "thing_id", "kind"),
        Index(
            "uq_thing_dates_primary_kind",
            "thing_id",
            "kind",
            unique=True,
            postgresql_where=sa_text("is_primary"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    thing_id: Mapped[UUID] = mapped_column(ForeignKey("things.id"))
    kind: Mapped[str] = mapped_column(String(80))
    value: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone_name: Mapped[str] = mapped_column(String(64))
    precision: Mapped[DatePrecision] = mapped_column(Enum(DatePrecision, name="date_precision"))
    certainty: Mapped[DateCertainty] = mapped_column(Enum(DateCertainty, name="date_certainty"))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    source_id: Mapped[UUID | None]
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StateMutationORM(Base):
    __tablename__ = "state_mutations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    thing_id: Mapped[UUID] = mapped_column(ForeignKey("things.id"))
    run_id: Mapped[UUID | None]
    action_id: Mapped[str] = mapped_column(String(120))
    mutation_type: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[UUID]
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)
    source_id: Mapped[UUID | None]
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TimelineEventORM(Base):
    __tablename__ = "timeline_events"
    __table_args__ = (Index("ix_timeline_thing_occurred", "thing_id", "occurred_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    thing_id: Mapped[UUID] = mapped_column(ForeignKey("things.id"))
    event_type: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_id: Mapped[UUID | None]
    mutation_id: Mapped[UUID | None] = mapped_column(ForeignKey("state_mutations.id"))
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceORM(Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_sources_user_idempotency"),
        Index("ix_sources_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType, name="source_type"))
    origin: Mapped[SourceOrigin] = mapped_column(Enum(SourceOrigin, name="source_origin"))
    title: Mapped[str] = mapped_column(String(300))
    mime_type: Mapped[str] = mapped_column(String(200))
    object_key: Mapped[str] = mapped_column(String(500), unique=True)
    external_url: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus, name="source_processing_status")
    )
    extracted_text: Mapped[str | None] = mapped_column(Text)
    processing_error: Mapped[str | None] = mapped_column(String(100))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_claim_owner: Mapped[str | None] = mapped_column(String(200))
    processing_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    processing_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    processing_attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_processing_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    idempotency_key: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ThingSourceORM(Base):
    __tablename__ = "thing_sources"

    thing_id: Mapped[UUID] = mapped_column(ForeignKey("things.id"), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id"), primary_key=True)
    relation_type: Mapped[SourceRelationType] = mapped_column(
        Enum(SourceRelationType, name="source_relation_type")
    )
    relevance: Mapped[float]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemoryORM(Base):
    __tablename__ = "long_term_memories"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_memories_user_idempotency"),
        Index("ix_memories_user_status_type", "user_id", "status", "memory_type"),
        Index("ix_memories_thing_status", "thing_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    memory_type: Mapped[MemoryType] = mapped_column(Enum(MemoryType, name="memory_type"))
    content: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    importance: Mapped[float]
    confidence: Mapped[float]
    thing_id: Mapped[UUID | None] = mapped_column(ForeignKey("things.id"))
    source_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), default=list)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    status: Mapped[MemoryStatus] = mapped_column(Enum(MemoryStatus, name="memory_status"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemoryOperationORM(Base):
    __tablename__ = "memory_operations"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_memory_operations_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    memory_id: Mapped[UUID] = mapped_column(ForeignKey("long_term_memories.id"))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    target_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BlockerORM(Base):
    __tablename__ = "blockers"
    __table_args__ = (Index("ix_blockers_thing_status", "thing_id", "status"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    thing_id: Mapped[UUID] = mapped_column(ForeignKey("things.id"))
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("tasks.id"))
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[BlockerSeverity] = mapped_column(
        Enum(BlockerSeverity, name="blocker_severity")
    )
    status: Mapped[BlockerStatus] = mapped_column(Enum(BlockerStatus, name="blocker_status"))
    blocked_since: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_id: Mapped[UUID | None]
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ThingRelationORM(Base):
    __tablename__ = "thing_relations"

    from_thing_id: Mapped[UUID] = mapped_column(ForeignKey("things.id"), primary_key=True)
    to_thing_id: Mapped[UUID] = mapped_column(ForeignKey("things.id"), primary_key=True)
    relation_type: Mapped[ThingRelationType] = mapped_column(
        Enum(ThingRelationType, name="thing_relation_type"), primary_key=True
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AutomationORM(Base):
    __tablename__ = "automations"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_automations_user_key"),
        Index("ix_automations_due", "status", "next_trigger_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    automation_type: Mapped[AutomationType] = mapped_column(
        Enum(AutomationType, name="automation_type")
    )
    title: Mapped[str] = mapped_column(String(300))
    message: Mapped[str] = mapped_column(Text)
    timezone_name: Mapped[str] = mapped_column(String(100))
    next_trigger_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    thing_id: Mapped[UUID | None] = mapped_column(ForeignKey("things.id"))
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("tasks.id"))
    source_id: Mapped[UUID | None] = mapped_column(ForeignKey("sources.id"))
    recurrence_interval_seconds: Mapped[int | None]
    status: Mapped[AutomationStatus] = mapped_column(
        Enum(AutomationStatus, name="automation_status")
    )
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AutomationOperationORM(Base):
    __tablename__ = "automation_operations"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_automation_operations_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    automation_id: Mapped[UUID] = mapped_column(ForeignKey("automations.id"))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    target_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationOutboxORM(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (
        UniqueConstraint("occurrence_key", name="uq_notification_occurrence"),
        Index("ix_notification_outbox_status_created", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    automation_id: Mapped[UUID] = mapped_column(ForeignKey("automations.id"))
    occurrence_key: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(300))
    message: Mapped[str] = mapped_column(Text)
    thing_id: Mapped[UUID | None] = mapped_column(ForeignKey("things.id"))
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, name="notification_status")
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AttentionFeedbackORM(Base):
    __tablename__ = "attention_feedback"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    subject_type: Mapped[AttentionSubjectType] = mapped_column(
        Enum(AttentionSubjectType, name="attention_subject_type"), primary_key=True
    )
    subject_id: Mapped[UUID] = mapped_column(primary_key=True)
    last_surfaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    surface_count: Mapped[int] = mapped_column(Integer, default=0)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ThreadORM(Base):
    __tablename__ = "threads"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_threads_user_key"),
        Index("ix_threads_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(300))
    active_thing_id: Mapped[UUID | None] = mapped_column(ForeignKey("things.id"))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentRunORM(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_agent_runs_user_key"),
        Index("ix_agent_runs_thread_created", "thread_id", "created_at"),
        Index("ix_agent_runs_status_updated", "status", "updated_at"),
        Index("ix_agent_runs_status_lease", "status", "lease_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    thread_id: Mapped[UUID] = mapped_column(ForeignKey("threads.id"))
    trigger: Mapped[RunTrigger] = mapped_column(Enum(RunTrigger, name="run_trigger"))
    input_message_id: Mapped[UUID | None]
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus, name="run_status"))
    current_phase: Mapped[str | None] = mapped_column(String(100))
    status_label: Mapped[str | None] = mapped_column(String(300))
    final_message_id: Mapped[UUID | None]
    interrupt_id: Mapped[UUID | None]
    interrupt: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    resume_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(100))
    claim_owner: Mapped[str | None] = mapped_column(String(200))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MessageORM(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_thread_created", "thread_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    thread_id: Mapped[UUID] = mapped_column(ForeignKey("threads.id"))
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole, name="message_role"))
    content: Mapped[str] = mapped_column(Text)
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_runs.id"))
    source_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), default=list)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RunEventORM(Base):
    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_run_events_sequence"),
        Index("ix_run_events_run_sequence", "run_id", "sequence"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"))
    sequence: Mapped[int]
    event_type: Mapped[RunEventType] = mapped_column(
        Enum(
            RunEventType,
            name="run_event_type",
            values_callable=lambda enum: [event.value for event in enum],
        )
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RunOperationORM(Base):
    __tablename__ = "run_operations"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_run_operations_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    operation: Mapped[str] = mapped_column(String(30))
    target_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ToolExecutionORM(Base):
    __tablename__ = "tool_executions"
    __table_args__ = (
        UniqueConstraint("run_id", "action_id", name="uq_tool_executions_action"),
        Index("ix_tool_executions_status_lease", "status", "lease_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"))
    action_id: Mapped[str] = mapped_column(String(200))
    tool_name: Mapped[str] = mapped_column(String(200))
    arguments_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[ToolExecutionStatus] = mapped_column(
        Enum(ToolExecutionStatus, name="tool_execution_status")
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    claim_owner: Mapped[str] = mapped_column(String(200))
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
