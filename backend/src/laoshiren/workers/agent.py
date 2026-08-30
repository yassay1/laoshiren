import asyncio
import hashlib
import json
import logging
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from laoshiren.agent.contracts import AgentBudgetExceeded, GraphState, ToolStatus
from laoshiren.agent.graph import ToolOutcomeUnknown
from laoshiren.agent.model_gateway import ModelGatewayError
from laoshiren.agent.tools import ToolReplayPolicy
from laoshiren.application.memories.candidate import is_explicit_memory_command
from laoshiren.application.memories.formation import MemoryFormationEvent
from laoshiren.application.runtime.dto import (
    CheckpointReconciliation,
    reconcile_checkpoint,
)
from laoshiren.application.runtime.ports import CheckpointInspector
from laoshiren.application.runtime.service import RuntimeApplicationService
from laoshiren.domain.runtime.entities import RunEventType, RunStatus
from laoshiren.workers.memory import MemoryFormationWorker

logger = logging.getLogger(__name__)


class RuntimeToolExecutionLedger:
    def __init__(
        self,
        runtime: RuntimeApplicationService,
        *,
        owner: str,
        lease_seconds: float,
    ) -> None:
        self._runtime = runtime
        self._owner = owner
        self._lease_seconds = lease_seconds
        self._claim_tokens: dict[tuple[UUID, str], UUID] = {}

    async def claim(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        run_claim_token: UUID,
        action_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        replay_policy: ToolReplayPolicy,
        idempotency_key: str,
    ) -> tuple[bool, dict[str, Any] | None]:
        canonical = json.dumps(
            arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        claim = await self._runtime.claim_tool_execution(
            run_id=run_id,
            user_id=user_id,
            action_id=action_id,
            tool_name=tool_name,
            arguments_hash=hashlib.sha256(canonical).hexdigest(),
            owner=self._owner,
            lease_seconds=self._lease_seconds,
            run_claim_token=run_claim_token,
            replay_safe=replay_policy is not ToolReplayPolicy.NON_REPLAYABLE,
            idempotency_key=idempotency_key,
        )
        if claim.blocked_reason is not None:
            raise ToolOutcomeUnknown(claim.blocked_reason)
        if claim.acquired:
            if claim.claim_token is None:
                raise RuntimeError("Tool claim did not return its fencing token.")
            self._claim_tokens[(run_id, action_id)] = claim.claim_token
        return claim.acquired, claim.cached_result

    async def complete(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        action_id: str,
        result: dict[str, Any],
        succeeded: bool,
    ) -> None:
        claim_token = self._claim_tokens.pop((run_id, action_id), None)
        if claim_token is None:
            raise RuntimeError("Tool completion is missing its fencing token.")
        await self._runtime.complete_tool_execution(
            run_id=run_id,
            user_id=user_id,
            action_id=action_id,
            owner=self._owner,
            claim_token=claim_token,
            result=result,
            succeeded=succeeded,
        )

    def claim_token_for(self, *, run_id: UUID, action_id: str) -> UUID | None:
        return self._claim_tokens.get((run_id, action_id))

    @property
    def claim_owner(self) -> str:
        return self._owner

    def acknowledge_atomic_completion(self, *, run_id: UUID, action_id: str) -> None:
        self._claim_tokens.pop((run_id, action_id), None)


class RuntimeAgentEventSink:
    def __init__(self, runtime: RuntimeApplicationService) -> None:
        self._runtime = runtime

    async def tool_started(
        self, *, user_id: UUID, run_id: UUID, action_id: str, tool_name: str
    ) -> None:
        await self._runtime.emit_event(
            user_id=user_id,
            run_id=run_id,
            event_type=RunEventType.TOOL_STARTED,
            data={"action_id": action_id, "tool_name": tool_name},
        )

    async def tool_finished(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        action_id: str,
        tool_name: str,
        status: ToolStatus,
        code: str,
    ) -> None:
        event_type = (
            RunEventType.TOOL_COMPLETED
            if status in {ToolStatus.SUCCESS, ToolStatus.PARTIAL}
            else RunEventType.TOOL_FAILED
        )
        await self._runtime.emit_event(
            user_id=user_id,
            run_id=run_id,
            event_type=event_type,
            data={
                "action_id": action_id,
                "tool_name": tool_name,
                "status": str(status),
                "code": code,
            },
        )


class AgentRunWorker:
    """Runs one queued durable Run through the Executive Graph."""

    def __init__(
        self,
        runtime: RuntimeApplicationService,
        graph: CompiledStateGraph[GraphState, None, GraphState, GraphState],
        *,
        memory_formation: MemoryFormationWorker | None = None,
        worker_id: str | None = None,
        lease_seconds: float = 60.0,
        heartbeat_seconds: float = 15.0,
        max_active_wall_time_seconds: float = 300.0,
        checkpoint_inspector: CheckpointInspector | None = None,
    ) -> None:
        self._runtime = runtime
        self._graph = graph
        self._memory_formation = memory_formation
        self._worker_id = worker_id or f"agent-worker-{uuid4()}"
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        if max_active_wall_time_seconds <= 0:
            raise ValueError("Active wall-time budget must be positive.")
        self._max_active_wall_time_seconds = max_active_wall_time_seconds
        self._checkpoint_inspector = checkpoint_inspector

    async def run_once(self, *, user_id: UUID, run_id: UUID) -> RunStatus:
        run = await self._runtime.claim_run(
            user_id=user_id,
            run_id=run_id,
            owner=self._worker_id,
            lease_seconds=self._lease_seconds,
        )
        if run is None:
            return (await self._runtime.get_run(user_id=user_id, run_id=run_id)).status
        if run.claim_token is None:
            raise RuntimeError("Claimed Run did not return its fencing token.")
        run_claim_token = run.claim_token
        raw_budget = getattr(run, "budget_snapshot", {})
        budget = raw_budget if isinstance(raw_budget, dict) else {}
        active_budget = float(
            budget.get("max_active_wall_time_seconds", self._max_active_wall_time_seconds)
        )
        active_since = run.active_started_at or datetime.now(UTC)
        active_elapsed = (
            run.active_time_used_ms / 1000 + (datetime.now(UTC) - active_since).total_seconds()
        )
        remaining_active_seconds = active_budget - active_elapsed
        if remaining_active_seconds <= 0:
            await self._runtime.fail_run(
                user_id=user_id,
                run_id=run_id,
                error_code="BUDGET_EXHAUSTED",
                claim_owner=self._worker_id,
                claim_token=run_claim_token,
            )
            return RunStatus.FAILED
        if run.terminal_output is not None:
            response = run.terminal_output.get("final_response")
            if not isinstance(response, str) or not response.strip():
                await self._runtime.fail_run(
                    user_id=user_id,
                    run_id=run_id,
                    error_code="RUNTIME_INCONSISTENCY",
                    claim_owner=self._worker_id,
                    claim_token=run_claim_token,
                )
                return RunStatus.FAILED
            await self._runtime.complete_run(
                user_id=user_id,
                run_id=run_id,
                content=response,
                claim_owner=self._worker_id,
                claim_token=run_claim_token,
            )
            return RunStatus.COMPLETED
        if self._checkpoint_inspector is not None:
            checkpoint = await self._checkpoint_inspector.inspect(run_id=run_id)
            reconciliation = reconcile_checkpoint(
                run_status=getattr(run, "status", RunStatus.RUNNING),
                snapshot=checkpoint,
            )
            if reconciliation is CheckpointReconciliation.FAIL_INCONSISTENCY:
                await self._runtime.fail_run(
                    user_id=user_id,
                    run_id=run_id,
                    error_code="RUNTIME_INCONSISTENCY",
                    claim_owner=self._worker_id,
                    claim_token=run_claim_token,
                )
                return RunStatus.FAILED
            if reconciliation is CheckpointReconciliation.FINALIZE:
                assert checkpoint.terminal_output is not None
                await self._runtime.accept_terminal_output(
                    user_id=user_id,
                    run_id=run_id,
                    output=checkpoint.terminal_output,
                    claim_owner=self._worker_id,
                    claim_token=run_claim_token,
                )
                response = checkpoint.terminal_output.get("final_response")
                if not isinstance(response, str) or not response.strip():
                    raise RuntimeError("Terminal checkpoint output is invalid.")
                await self._runtime.complete_run(
                    user_id=user_id,
                    run_id=run_id,
                    content=response,
                    claim_owner=self._worker_id,
                    claim_token=run_claim_token,
                )
                return RunStatus.COMPLETED
            if reconciliation is CheckpointReconciliation.WAIT_FOR_USER:
                assert checkpoint.pending_interrupt is not None
                checkpoint_payload = dict(checkpoint.pending_interrupt)
                checkpoint_interaction_id: UUID | None = None
                if checkpoint.pending_interrupt_id is not None:
                    checkpoint_payload.setdefault("interaction_id", checkpoint.pending_interrupt_id)
                    try:
                        checkpoint_interaction_id = UUID(checkpoint.pending_interrupt_id)
                    except ValueError:
                        # LangGraph providers may use non-UUID interrupt keys;
                        # the durable Run interaction then gets a local UUID.
                        checkpoint_interaction_id = None
                await self._runtime.require_input(
                    user_id=user_id,
                    run_id=run_id,
                    payload=checkpoint_payload,
                    interaction_id=checkpoint_interaction_id,
                    claim_owner=self._worker_id,
                    claim_token=run_claim_token,
                )
                return RunStatus.WAITING_FOR_USER
        logger.info(
            "agent_run_claimed",
            extra={
                "run_id": str(run_id),
                "thread_id": str(run.thread_id),
                "user_id": str(user_id),
                "worker_id": self._worker_id,
                "attempt_count": run.attempt_count,
            },
        )
        messages = await self._runtime.list_messages(
            user_id=user_id, thread_id=run.thread_id, limit=500
        )
        lease_lost = asyncio.Event()

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(self._heartbeat_seconds)
                renewed = await self._runtime.renew_run_lease(
                    user_id=user_id,
                    run_id=run_id,
                    owner=self._worker_id,
                    claim_token=run_claim_token,
                    lease_seconds=self._lease_seconds,
                )
                if not renewed:
                    lease_lost.set()
                    return

        heartbeat_task = asyncio.create_task(heartbeat(), name=f"run-heartbeat-{run_id}")
        # LangGraph's thread_id identifies one checkpoint execution lifecycle.
        # Business Thread history is separate; every Run gets an isolated checkpoint.
        config: RunnableConfig = {"configurable": {"thread_id": str(run.id)}}
        try:
            if run.resume_payload is not None:
                command: Command[Any] = Command(
                    resume=run.resume_payload,
                    update={"run_claim_token": str(run_claim_token)},
                )
                try:
                    async with asyncio.timeout(remaining_active_seconds):
                        output = cast(
                            dict[str, Any],
                            await self._graph.ainvoke(command, config, durability="sync"),
                        )
                except TimeoutError as exception:
                    raise AgentBudgetExceeded(
                        "Run active wall-time budget exceeded."
                    ) from exception
            else:
                current = next(item for item in messages if item.id == run.input_message_id)
                initial: GraphState = {
                    "user_id": str(user_id),
                    "thread_id": str(run.thread_id),
                    "run_id": str(run_id),
                    "run_claim_token": str(run_claim_token),
                    "input_message_id": str(run.input_message_id),
                    "budget_snapshot": dict(budget),
                    "current_input": current.content,
                    "messages": [],
                    "source_refs": [str(value) for value in current.source_ids],
                    "tool_results": [],
                }
                try:
                    async with asyncio.timeout(remaining_active_seconds):
                        output = cast(
                            dict[str, Any],
                            await self._graph.ainvoke(initial, config, durability="sync"),
                        )
                except TimeoutError as exception:
                    raise AgentBudgetExceeded(
                        "Run active wall-time budget exceeded."
                    ) from exception
            interrupts = output.get("__interrupt__")
            if interrupts:
                first = interrupts[0]
                payload: Any = first.value
                if not isinstance(payload, dict):
                    payload = {"type": "input", "message": str(payload)}
                await self._runtime.require_input(
                    user_id=user_id,
                    run_id=run_id,
                    payload=payload,
                    claim_owner=self._worker_id,
                    claim_token=run_claim_token,
                )
                return RunStatus.WAITING_FOR_USER
            response = output.get("final_response")
            if not isinstance(response, str) or not response.strip():
                raise RuntimeError("Executive Graph ended without a response.")
            if lease_lost.is_set():
                raise RuntimeError("Run lease was lost during execution.")
            await self._runtime.accept_terminal_output(
                user_id=user_id,
                run_id=run_id,
                output={"final_response": response.strip()},
                claim_owner=self._worker_id,
                claim_token=run_claim_token,
            )
            await self._runtime.complete_run(
                user_id=user_id,
                run_id=run_id,
                content=response,
                claim_owner=self._worker_id,
                claim_token=run_claim_token,
            )
            logger.info(
                "agent_run_completed",
                extra={
                    "run_id": str(run_id),
                    "thread_id": str(run.thread_id),
                    "user_id": str(user_id),
                    "worker_id": self._worker_id,
                },
            )
            if self._memory_formation is not None:
                current = next(item for item in messages if item.id == run.input_message_id)
                tool_codes = tuple(
                    str(result.get("code", ""))
                    for result in output.get("tool_results", [])
                    if result.get("status") == "SUCCESS"
                )
                event = MemoryFormationEvent(
                    user_id=user_id,
                    run_id=run_id,
                    thread_id=run.thread_id,
                    source_message_id=current.id,
                    user_text=current.content,
                    tool_result_codes=tool_codes,
                )
                if is_explicit_memory_command(current.content):
                    await self._memory_formation.process(event)
                else:
                    await self._memory_formation.enqueue_durable(event)
            return RunStatus.COMPLETED
        except Exception as exception:
            if isinstance(exception, AgentBudgetExceeded):
                error_code = "BUDGET_EXHAUSTED"
            elif isinstance(exception, ToolOutcomeUnknown):
                error_code = "TOOL_OUTCOME_UNKNOWN"
            elif isinstance(exception, ModelGatewayError):
                error_code = exception.code
            else:
                error_code = "AGENT_EXECUTION_FAILED"
            await self._runtime.fail_run(
                user_id=user_id,
                run_id=run_id,
                error_code=error_code,
                claim_owner=self._worker_id,
                claim_token=run_claim_token,
            )
            logger.exception(
                "agent_run_failed",
                extra={
                    "run_id": str(run_id),
                    "thread_id": str(run.thread_id),
                    "user_id": str(user_id),
                    "worker_id": self._worker_id,
                    "error_code": error_code,
                },
            )
            raise
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
