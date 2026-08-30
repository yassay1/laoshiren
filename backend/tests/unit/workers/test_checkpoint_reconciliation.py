from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from laoshiren.application.runtime.dto import (
    CheckpointReconciliation,
    CheckpointSnapshotDTO,
    reconcile_checkpoint,
)
from laoshiren.domain.runtime.entities import RunStatus
from laoshiren.workers.agent import AgentRunWorker


class Inspector:
    def __init__(self, snapshot: CheckpointSnapshotDTO) -> None:
        self.snapshot = snapshot

    async def inspect(self, *, run_id: UUID) -> CheckpointSnapshotDTO:
        return self.snapshot


class Runtime:
    def __init__(self) -> None:
        self.run_id = uuid4()
        self.user_id = uuid4()
        self.claim_token = uuid4()
        self.required_input: dict[str, Any] | None = None
        self.accepted_output: dict[str, Any] | None = None
        self.completed_content: str | None = None
        self.failed_code: str | None = None

    async def claim_run(self, **_: Any) -> Any:
        return SimpleNamespace(
            id=self.run_id,
            claim_token=self.claim_token,
            active_started_at=datetime.now(UTC),
            active_time_used_ms=0,
            terminal_output=None,
        )

    async def require_input(self, *, payload: dict[str, Any], **_: Any) -> None:
        self.required_input = payload

    async def accept_terminal_output(self, *, output: dict[str, Any], **_: Any) -> None:
        self.accepted_output = output

    async def complete_run(self, *, content: str, **_: Any) -> None:
        self.completed_content = content

    async def fail_run(self, *, error_code: str, **_: Any) -> None:
        self.failed_code = error_code


@pytest.mark.parametrize(
    ("status", "snapshot", "expected"),
    [
        (
            RunStatus.RUNNING,
            CheckpointSnapshotDTO(exists=True, terminal_output={"final_response": "ok"}),
            CheckpointReconciliation.FINALIZE,
        ),
        (
            RunStatus.RUNNING,
            CheckpointSnapshotDTO(exists=True, pending_interrupt={"type": "input"}),
            CheckpointReconciliation.WAIT_FOR_USER,
        ),
        (
            RunStatus.RUNNING,
            CheckpointSnapshotDTO(
                exists=True,
                pending_actions=({"action_id": "a", "tool_name": "state_get_thing_context"},),
            ),
            CheckpointReconciliation.RECONCILE_TOOLS,
        ),
        (
            RunStatus.RUNNING,
            CheckpointSnapshotDTO(exists=True, pending_actions=({"action_id": "a"},)),
            CheckpointReconciliation.FAIL_INCONSISTENCY,
        ),
        (
            RunStatus.WAITING_FOR_USER,
            CheckpointSnapshotDTO(exists=False),
            CheckpointReconciliation.FAIL_INCONSISTENCY,
        ),
        (
            RunStatus.RUNNING,
            CheckpointSnapshotDTO(exists=False),
            CheckpointReconciliation.REEXECUTE,
        ),
    ],
)
def test_checkpoint_reconciliation_is_deterministic(
    status: RunStatus,
    snapshot: CheckpointSnapshotDTO,
    expected: CheckpointReconciliation,
) -> None:
    assert reconcile_checkpoint(run_status=status, snapshot=snapshot) is expected


@pytest.mark.asyncio
async def test_interrupt_checkpoint_reconciles_without_graph_execution() -> None:
    runtime = Runtime()
    worker = AgentRunWorker(
        cast(Any, runtime),
        cast(Any, object()),
        checkpoint_inspector=Inspector(
            CheckpointSnapshotDTO(
                exists=True,
                pending_interrupt={"type": "CLARIFICATION", "question": "哪一个？"},
            )
        ),
    )
    status = await worker.run_once(user_id=runtime.user_id, run_id=runtime.run_id)
    assert status is RunStatus.WAITING_FOR_USER
    assert runtime.required_input == {
        "type": "CLARIFICATION",
        "question": "哪一个？",
    }


@pytest.mark.asyncio
async def test_terminal_checkpoint_reconciles_without_graph_execution() -> None:
    runtime = Runtime()
    output = {"final_response": "从 checkpoint 完成。"}
    worker = AgentRunWorker(
        cast(Any, runtime),
        cast(Any, object()),
        checkpoint_inspector=Inspector(CheckpointSnapshotDTO(exists=True, terminal_output=output)),
    )
    status = await worker.run_once(user_id=runtime.user_id, run_id=runtime.run_id)
    assert status is RunStatus.COMPLETED
    assert runtime.accepted_output == output
    assert runtime.completed_content == "从 checkpoint 完成。"


@pytest.mark.asyncio
async def test_malformed_pending_action_fails_without_graph_execution() -> None:
    runtime = Runtime()
    worker = AgentRunWorker(
        cast(Any, runtime),
        cast(Any, object()),
        checkpoint_inspector=Inspector(
            CheckpointSnapshotDTO(exists=True, pending_actions=({"action_id": "a"},))
        ),
    )
    status = await worker.run_once(user_id=runtime.user_id, run_id=runtime.run_id)
    assert status is RunStatus.FAILED
    assert runtime.failed_code == "RUNTIME_INCONSISTENCY"
