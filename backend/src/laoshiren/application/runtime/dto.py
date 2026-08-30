from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from laoshiren.domain.runtime.entities import (
    MessageRole,
    RunEventType,
    RunStatus,
    RunTrigger,
)


@dataclass(frozen=True, slots=True)
class ThreadDTO:
    id: UUID
    title: str
    active_thing_id: UUID | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class MessageDTO:
    id: UUID
    thread_id: UUID
    role: MessageRole
    content: str
    run_id: UUID | None
    source_ids: list[UUID]
    metadata: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RunDTO:
    id: UUID
    thread_id: UUID
    trigger: RunTrigger
    input_message_id: UUID | None
    status: RunStatus
    current_phase: str | None
    status_label: str | None
    final_message_id: UUID | None
    interrupt_id: UUID | None
    interrupt: dict[str, Any] | None
    resume_payload: dict[str, Any] | None
    error_code: str | None
    claim_owner: str | None
    claim_token: UUID | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    attempt_count: int
    version: int
    last_event_sequence: int
    pending_interaction: dict[str, Any] | None
    active_time_used_ms: int
    active_started_at: datetime | None
    terminal_output: dict[str, Any] | None
    graph_terminal_at: datetime | None
    budget_snapshot: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime
    stream_url: str
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class RunEventDTO:
    id: UUID
    run_id: UUID
    sequence: int
    event: RunEventType
    occurred_at: datetime
    data: dict[str, Any]
    visibility: str
    schema_version: int


@dataclass(frozen=True, slots=True)
class ToolExecutionClaimDTO:
    acquired: bool
    claim_token: UUID | None = None
    cached_result: dict[str, Any] | None = None
    blocked_reason: str | None = None


@dataclass(frozen=True, slots=True)
class DurableJobClaimDTO:
    job_id: UUID
    user_id: UUID
    run_id: UUID
    claim_epoch: int


@dataclass(frozen=True, slots=True)
class CheckpointSnapshotDTO:
    exists: bool
    terminal_output: dict[str, Any] | None = None
    pending_interrupt: dict[str, Any] | None = None
    pending_actions: tuple[dict[str, Any], ...] = ()
    pending_interrupt_id: str | None = None


@dataclass(frozen=True, slots=True)
class ContextAssemblyRequestDTO:
    """References needed to rebuild model context for one invocation.

    The request deliberately contains stable identifiers and user input only;
    it must not carry a checkpoint's stale State/Memory snapshot.
    """

    user_id: UUID
    thread_id: UUID
    run_id: UUID
    input_message_id: UUID | None
    current_input: str
    source_refs: tuple[UUID, ...]
    decision_index: int


@dataclass(frozen=True, slots=True)
class ContextAssemblyDTO:
    """Bounded transient context for a single Executive invocation."""

    messages: list[dict[str, Any]]
    prefetched_state: dict[str, Any]
    context_manifest: dict[str, Any]


class CheckpointReconciliation(StrEnum):
    """Deterministic action selected from durable Run/checkpoint facts."""

    REEXECUTE = "REEXECUTE"
    RECONCILE_TOOLS = "RECONCILE_TOOLS"
    WAIT_FOR_USER = "WAIT_FOR_USER"
    FINALIZE = "FINALIZE"
    FAIL_INCONSISTENCY = "FAIL_INCONSISTENCY"


def reconcile_checkpoint(
    *, run_status: RunStatus, snapshot: CheckpointSnapshotDTO
) -> CheckpointReconciliation:
    """Return the recovery action without consulting a model or guessing state.

    A checkpoint terminal output is the graph's commit boundary.  An interrupt
    is authoritative for HITL.  A checkpoint with a pending action must be
    resumed so the Tool ledger can decide replay/takeover/unknown outcome.
    """

    if snapshot.terminal_output is not None:
        return CheckpointReconciliation.FINALIZE
    if snapshot.pending_interrupt is not None:
        return CheckpointReconciliation.WAIT_FOR_USER
    if snapshot.pending_actions:
        if any(
            not isinstance(action.get("action_id"), str)
            or not action["action_id"].strip()
            or not isinstance(action.get("tool_name"), str)
            or not action["tool_name"].strip()
            for action in snapshot.pending_actions
        ):
            return CheckpointReconciliation.FAIL_INCONSISTENCY
        return CheckpointReconciliation.RECONCILE_TOOLS
    if run_status is RunStatus.WAITING_FOR_USER:
        return CheckpointReconciliation.FAIL_INCONSISTENCY
    return CheckpointReconciliation.REEXECUTE


@dataclass(frozen=True, slots=True)
class EphemeralFrameDTO:
    run_id: UUID
    frame_type: str
    data: dict[str, Any]
    emitted_at: datetime = field(default_factory=lambda: datetime.now(UTC))
