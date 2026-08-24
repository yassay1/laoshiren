import asyncio
import hashlib
import json
from contextlib import suppress
from typing import Any, cast
from uuid import UUID, uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from laoshiren.agent.contracts import AgentBudgetExceeded, GraphState, ToolStatus
from laoshiren.application.memories.context import AgentMemoryApplicationService
from laoshiren.application.runtime.service import RuntimeApplicationService
from laoshiren.application.sources.service import SourceApplicationService
from laoshiren.domain.runtime.entities import RunEventType, RunStatus


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

    async def claim(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        action_id: str,
        tool_name: str,
        arguments: dict[str, Any],
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
        )
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
        await self._runtime.complete_tool_execution(
            run_id=run_id,
            user_id=user_id,
            action_id=action_id,
            owner=self._owner,
            result=result,
            succeeded=succeeded,
        )


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
            if status is ToolStatus.SUCCESS
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
        agent_memory: AgentMemoryApplicationService | None = None,
        sources: SourceApplicationService | None = None,
        *,
        worker_id: str | None = None,
        lease_seconds: float = 60.0,
        heartbeat_seconds: float = 15.0,
    ) -> None:
        self._runtime = runtime
        self._graph = graph
        self._agent_memory = agent_memory
        self._sources = sources
        self._worker_id = worker_id or f"agent-worker-{uuid4()}"
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds

    async def run_once(self, *, user_id: UUID, run_id: UUID) -> RunStatus:
        run = await self._runtime.claim_run(
            user_id=user_id,
            run_id=run_id,
            owner=self._worker_id,
            lease_seconds=self._lease_seconds,
        )
        if run is None:
            return (await self._runtime.get_run(user_id=user_id, run_id=run_id)).status
        messages = await self._runtime.list_messages(
            user_id=user_id, thread_id=run.thread_id, limit=100
        )
        lease_lost = asyncio.Event()

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(self._heartbeat_seconds)
                renewed = await self._runtime.renew_run_lease(
                    user_id=user_id,
                    run_id=run_id,
                    owner=self._worker_id,
                    lease_seconds=self._lease_seconds,
                )
                if not renewed:
                    lease_lost.set()
                    return

        heartbeat_task = asyncio.create_task(
            heartbeat(), name=f"run-heartbeat-{run_id}"
        )
        # LangGraph's thread_id identifies one checkpoint execution lifecycle.
        # Business Thread history is separate; every Run gets an isolated checkpoint.
        config: RunnableConfig = {"configurable": {"thread_id": str(run.id)}}
        try:
            if run.resume_payload is not None:
                command: Command[Any] = Command(resume=run.resume_payload)
                output = cast(
                    dict[str, Any],
                    await self._graph.ainvoke(command, config, durability="sync"),
                )
            else:
                current = next(item for item in messages if item.id == run.input_message_id)
                initial: GraphState = {
                    "user_id": str(user_id),
                    "thread_id": str(run.thread_id),
                    "run_id": str(run_id),
                    "current_input": current.content,
                    "messages": [
                        {"role": item.role, "content": item.content} for item in messages
                    ],
                    "source_refs": [str(value) for value in current.source_ids],
                    "tool_results": [],
                }
                if self._agent_memory is not None:
                    memory_context = await self._agent_memory.load_context(
                        user_id=user_id, query=current.content
                    )
                    initial["prefetched_state"] = {
                        "memory_context": memory_context.as_prompt_data()
                    }
                if self._sources is not None and current.source_ids:
                    source_context: list[dict[str, str]] = []
                    remaining = 12_000
                    for source_id in current.source_ids[:5]:
                        source = await self._sources.get(
                            user_id=user_id, source_id=source_id
                        )
                        chunks = await self._sources.get_context_chunks(
                            user_id=user_id,
                            source_id=source_id,
                            max_chunks=8,
                            max_characters=remaining,
                            query=current.content,
                        )
                        if not chunks and source.extracted_text and remaining > 0:
                            # Compatibility for READY rows created before chunk migration.
                            excerpt = source.extracted_text[:remaining]
                            source_context.append(
                                {
                                    "source_id": str(source.id),
                                    "chunk_id": "",
                                    "ordinal": "0",
                                    "title": source.title,
                                    "content": excerpt,
                                }
                            )
                            remaining -= len(excerpt)
                        for chunk in chunks:
                            if remaining <= 0:
                                break
                            source_context.append(
                                {
                                    "source_id": str(source.id),
                                    "chunk_id": str(chunk.id),
                                    "ordinal": str(chunk.ordinal),
                                    "page_number": (
                                        str(chunk.page_number)
                                        if chunk.page_number is not None
                                        else ""
                                    ),
                                    "title": source.title,
                                    "content": chunk.content,
                                }
                            )
                            remaining -= len(chunk.content)
                    initial.setdefault("prefetched_state", {})[
                        "source_context"
                    ] = source_context
                output = cast(
                    dict[str, Any],
                    await self._graph.ainvoke(initial, config, durability="sync"),
                )
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
                )
                return RunStatus.WAITING_USER
            response = output.get("final_response")
            if not isinstance(response, str) or not response.strip():
                raise RuntimeError("Executive Graph ended without a response.")
            if lease_lost.is_set():
                raise RuntimeError("Run lease was lost during execution.")
            if self._agent_memory is not None:
                current = next(item for item in messages if item.id == run.input_message_id)
                await self._agent_memory.form_from_user_input(
                    user_id=user_id, run_id=run_id, text=current.content
                )
            await self._runtime.complete_run(
                user_id=user_id,
                run_id=run_id,
                content=response,
                claim_owner=self._worker_id,
            )
            return RunStatus.COMPLETED
        except Exception as exception:
            error_code = (
                "AGENT_BUDGET_EXCEEDED"
                if isinstance(exception, AgentBudgetExceeded)
                else "AGENT_EXECUTION_FAILED"
            )
            await self._runtime.fail_run(
                user_id=user_id,
                run_id=run_id,
                error_code=error_code,
                claim_owner=self._worker_id,
            )
            raise
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
