from typing import Any, cast
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from laoshiren.agent.contracts import AgentBudgetExceeded, GraphState, ToolStatus
from laoshiren.application.memories.context import AgentMemoryApplicationService
from laoshiren.application.runtime.service import RuntimeApplicationService
from laoshiren.application.sources.service import SourceApplicationService
from laoshiren.domain.runtime.entities import RunEventType, RunStatus


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
    ) -> None:
        self._runtime = runtime
        self._graph = graph
        self._agent_memory = agent_memory
        self._sources = sources

    async def run_once(self, *, user_id: UUID, run_id: UUID) -> RunStatus:
        run = await self._runtime.get_run(user_id=user_id, run_id=run_id)
        if run.status is not RunStatus.QUEUED:
            return run.status
        messages = await self._runtime.list_messages(
            user_id=user_id, thread_id=run.thread_id, limit=100
        )
        await self._runtime.start_run(
            user_id=user_id,
            run_id=run_id,
            phase="executive",
            label="正在理解并处理",
        )
        # LangGraph's thread_id identifies one checkpoint execution lifecycle.
        # Business Thread history is separate; every Run gets an isolated checkpoint.
        config: RunnableConfig = {"configurable": {"thread_id": str(run.id)}}
        try:
            if run.resume_payload is not None:
                command: Command[Any] = Command(resume=run.resume_payload)
                output = cast(dict[str, Any], await self._graph.ainvoke(command, config))
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
                        if source.extracted_text and remaining > 0:
                            excerpt = source.extracted_text[:remaining]
                            source_context.append(
                                {
                                    "source_id": str(source.id),
                                    "title": source.title,
                                    "content": excerpt,
                                }
                            )
                            remaining -= len(excerpt)
                    initial.setdefault("prefetched_state", {})[
                        "source_context"
                    ] = source_context
                output = cast(dict[str, Any], await self._graph.ainvoke(initial, config))
            interrupts = output.get("__interrupt__")
            if interrupts:
                first = interrupts[0]
                payload: Any = first.value
                if not isinstance(payload, dict):
                    payload = {"type": "input", "message": str(payload)}
                await self._runtime.require_input(
                    user_id=user_id, run_id=run_id, payload=payload
                )
                return RunStatus.WAITING_USER
            response = output.get("final_response")
            if not isinstance(response, str) or not response.strip():
                raise RuntimeError("Executive Graph ended without a response.")
            if self._agent_memory is not None:
                current = next(item for item in messages if item.id == run.input_message_id)
                await self._agent_memory.form_from_user_input(
                    user_id=user_id, run_id=run_id, text=current.content
                )
            await self._runtime.complete_run(user_id=user_id, run_id=run_id, content=response)
            return RunStatus.COMPLETED
        except Exception as exception:
            error_code = (
                "AGENT_BUDGET_EXCEEDED"
                if isinstance(exception, AgentBudgetExceeded)
                else "AGENT_EXECUTION_FAILED"
            )
            await self._runtime.fail_run(
                user_id=user_id, run_id=run_id, error_code=error_code
            )
            raise
