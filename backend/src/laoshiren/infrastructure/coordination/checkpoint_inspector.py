from typing import Any
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from laoshiren.application.runtime.dto import CheckpointSnapshotDTO


class LangGraphCheckpointInspector:
    """Maps LangGraph state into the provider-neutral Runtime recovery contract."""

    def __init__(self, graph: CompiledStateGraph[Any, Any, Any, Any]) -> None:
        self._graph = graph

    async def inspect(self, *, run_id: UUID) -> CheckpointSnapshotDTO:
        config: RunnableConfig = {"configurable": {"thread_id": str(run_id)}}
        snapshot = await self._graph.aget_state(config)
        values = snapshot.values if isinstance(snapshot.values, dict) else {}
        final_response = values.get("final_response")
        terminal_output = (
            {"final_response": final_response}
            if isinstance(final_response, str) and final_response.strip()
            else None
        )
        pending_interrupt: dict[str, Any] | None = None
        pending_interrupt_id: str | None = None
        if snapshot.interrupts:
            interrupt = snapshot.interrupts[0]
            pending_interrupt_id = str(interrupt.id) if interrupt.id is not None else None
            value = interrupt.value
            pending_interrupt = dict(value) if isinstance(value, dict) else {"value": value}
        actions: list[dict[str, Any]] = []
        pending_action = values.get("pending_action")
        if isinstance(pending_action, dict):
            actions.append(dict(pending_action))
        pending_batch = values.get("pending_batch")
        if isinstance(pending_batch, list):
            actions.extend(dict(item) for item in pending_batch if isinstance(item, dict))
        return CheckpointSnapshotDTO(
            exists=bool(snapshot.created_at or values or snapshot.next),
            terminal_output=terminal_output,
            pending_interrupt=pending_interrupt,
            pending_interrupt_id=pending_interrupt_id,
            pending_actions=tuple(actions),
        )
