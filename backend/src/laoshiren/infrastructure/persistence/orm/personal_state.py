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
from laoshiren.domain.automations.value_objects import (
    DeliveryStatus,
    MisfirePolicy,
    NotificationKind,
    OccurrenceStatus,
)
from laoshiren.domain.identity.value_objects import DevicePlatform, UserStatus
from laoshiren.domain.memories.entities import MemoryStatus, MemoryType
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
from laoshiren.domain.runtime.entities import (
    DurableJobKind,
    DurableJobStatus,
    MessageRole,
    RunEventType,
    RunInteractionStatus,
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
    __table_args__ = (
        Index(
            "uq_users_external_subject",
            "external_subject",
            unique=True,
            postgresql_where=sa_text("external_subject IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status"),
        default=UserStatus.ACTIVE,
    )
    external_subject: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeviceORM(Base):
    __tablename__ = "devices"
    __table_args__ = (Index("ix_devices_user_active", "user_id", "active"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    platform: Mapped[DevicePlatform] = mapped_column(Enum(DevicePlatform, name="device_platform"))
    timezone_name: Mapped[str] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BusinessSessionORM(Base):
    __tablename__ = "business_sessions"
    __table_args__ = (Index("ix_business_sessions_user", "user_id", "expires_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    device_id: Mapped[UUID | None] = mapped_column(ForeignKey("devices.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    merged_into_thing_id: Mapped[UUID | None] = mapped_column(ForeignKey("things.id"))


class TaskORM(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_thing_status", "thing_id", "status"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    thing_id: Mapped[UUID | None] = mapped_column(ForeignKey("things.id"))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus, name="task_status"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recurrence_interval_days: Mapped[int | None] = mapped_column(Integer)
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
    kind: Mapped[ThingDateType] = mapped_column(Enum(ThingDateType, name="thing_date_type"))
    label: Mapped[str | None] = mapped_column(String(200))
    value: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone_name: Mapped[str] = mapped_column(String(64))
    precision: Mapped[DatePrecision] = mapped_column(Enum(DatePrecision, name="date_precision"))
    certainty: Mapped[DateCertainty] = mapped_column(Enum(DateCertainty, name="date_certainty"))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    source_id: Mapped[UUID | None]
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ThingContextEntryORM(Base):
    __tablename__ = "thing_context_entries"
    __table_args__ = (Index("ix_thing_context_entries_thing_updated", "thing_id", "updated_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    thing_id: Mapped[UUID] = mapped_column(ForeignKey("things.id"))
    label: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text)
    source_id: Mapped[UUID | None]
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StateMutationORM(Base):
    __tablename__ = "state_mutations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    thing_id: Mapped[UUID | None] = mapped_column(ForeignKey("things.id"))
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
    processing_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_processing_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class SourceChunkORM(Base):
    __tablename__ = "source_chunks"
    __table_args__ = (
        UniqueConstraint("source_id", "ordinal", name="uq_source_chunks_ordinal"),
        Index("ix_source_chunks_source_ordinal", "source_id", "ordinal"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
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
    profile_key: Mapped[str | None] = mapped_column(String(100))
    supersedes_id: Mapped[UUID | None] = mapped_column(ForeignKey("long_term_memories.id"))
    provenance_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    source_message_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), default=list
    )
    status: Mapped[MemoryStatus] = mapped_column(Enum(MemoryStatus, name="memory_status"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemorySuppressionORM(Base):
    __tablename__ = "memory_suppressions"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "content_fingerprint",
            name="uq_memory_suppressions_user_fingerprint",
        ),
        Index("ix_memory_suppressions_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    content_fingerprint: Mapped[str] = mapped_column(String(64))
    memory_id: Mapped[UUID | None] = mapped_column(ForeignKey("long_term_memories.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    definition_revision: Mapped[int] = mapped_column(Integer, default=1)
    misfire_policy: Mapped[MisfirePolicy] = mapped_column(
        Enum(MisfirePolicy, name="misfire_policy"), default=MisfirePolicy.FIRE_ONCE
    )
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


class AutomationOccurrenceORM(Base):
    __tablename__ = "automation_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "automation_id",
            "definition_revision",
            "scheduled_for",
            name="uq_automation_occurrence_slot",
        ),
        Index("ix_automation_occurrences_status_created", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    automation_id: Mapped[UUID] = mapped_column(ForeignKey("automations.id"))
    definition_revision: Mapped[int]
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[OccurrenceStatus] = mapped_column(
        Enum(OccurrenceStatus, name="occurrence_status")
    )
    durable_job_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    materialized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PushEndpointORM(Base):
    __tablename__ = "push_endpoints"
    __table_args__ = (
        UniqueConstraint("user_id", "device_id", name="uq_push_endpoints_user_device"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id"))
    provider: Mapped[str] = mapped_column(String(50))
    push_token: Mapped[str] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationIntentORM(Base):
    __tablename__ = "notification_intents"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_notification_intents_dedupe"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[NotificationKind] = mapped_column(
        Enum(NotificationKind, name="notification_kind")
    )
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    occurrence_id: Mapped[UUID] = mapped_column(ForeignKey("automation_occurrences.id"))
    automation_id: Mapped[UUID] = mapped_column(ForeignKey("automations.id"))
    thing_id: Mapped[UUID | None] = mapped_column(ForeignKey("things.id"))
    dedupe_key: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationDeliveryORM(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "intent_id",
            "endpoint_id",
            name="uq_notification_deliveries_intent_endpoint",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    intent_id: Mapped[UUID] = mapped_column(ForeignKey("notification_intents.id"))
    endpoint_id: Mapped[UUID] = mapped_column(ForeignKey("push_endpoints.id"))
    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="delivery_status")
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    claim_owner: Mapped[str | None] = mapped_column(String(200))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    claim_token: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    active_time_used_ms: Mapped[int] = mapped_column(Integer, default=0)
    active_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    graph_terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    budget_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
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
    visibility: Mapped[str] = mapped_column(String(30), default="CLIENT")
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RunOperationORM(Base):
    __tablename__ = "run_operations"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key", name="uq_run_operations_key"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    operation: Mapped[str] = mapped_column(String(30))
    target_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RunInteractionORM(Base):
    __tablename__ = "run_interactions"
    __table_args__ = (Index("ix_run_interactions_run_status", "run_id", "status"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    action_id: Mapped[str | None] = mapped_column(String(200))
    interaction_type: Mapped[str] = mapped_column(String(50))
    status: Mapped[RunInteractionStatus] = mapped_column(
        Enum(RunInteractionStatus, name="run_interaction_status")
    )
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    receipt: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(100))
    provider_idempotency_key: Mapped[str | None] = mapped_column(String(300))
    provider_request_id: Mapped[str | None] = mapped_column(String(300))
    claim_owner: Mapped[str] = mapped_column(String(200))
    claim_token: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    replay_safe: Mapped[bool] = mapped_column(default=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(300))
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DurableJobORM(Base):
    __tablename__ = "durable_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_durable_jobs_user_dedupe"),
        Index(
            "ix_durable_jobs_ready_claim",
            "status",
            "available_at",
            "priority",
            "created_at",
        ),
        Index("ix_durable_jobs_lease", "status", "lease_until"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[DurableJobKind] = mapped_column(Enum(DurableJobKind, name="durable_job_kind"))
    dedupe_key: Mapped[str] = mapped_column(String(300))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[DurableJobStatus] = mapped_column(
        Enum(DurableJobStatus, name="durable_job_status")
    )
    priority: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivery_attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_delivery_attempts: Mapped[int] = mapped_column(Integer, default=5)
    claimed_by: Mapped[str | None] = mapped_column(String(200))
    claim_epoch: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
