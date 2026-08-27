from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from laoshiren.agent.contracts import (
    DecisionKind,
    ExecutiveDecision,
    GraphState,
    ToolCallSpec,
    ToolResult,
    ToolStatus,
)
from laoshiren.agent.graph import build_executive_graph
from laoshiren.agent.tools import (
    ToolDefinition,
    ToolExecutionContext,
    ToolRegistry,
    ToolRisk,
    register_search_tools,
)
from laoshiren.application.search.service import SearchApplicationService
from laoshiren.infrastructure.search.recording import RecordingWebSearchAdapter

pytestmark = pytest.mark.asyncio


class ParallelGateway:
    def __init__(self) -> None:
        self._phase = 0

    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
    ) -> ExecutiveDecision:
        del tool_manifest
        if self._phase == 0:
            self._phase += 1
            assert "search.official" in available_tools
            return ExecutiveDecision(
                DecisionKind.CALL_TOOLS,
                tool_calls=(
                    ToolCallSpec("search.official", {"query": "比赛截止"}),
                    ToolCallSpec("memory.search", {"query": "比赛"}),
                ),
            )
        return ExecutiveDecision(
            DecisionKind.RESPOND,
            content=f"done:{len(state.get('tool_results', []))}",
        )


def initial_state() -> GraphState:
    return {
        "user_id": str(uuid4()),
        "thread_id": str(uuid4()),
        "run_id": str(uuid4()),
        "run_claim_token": str(uuid4()),
        "current_input": "查官网截止并回忆背景",
        "messages": [],
        "source_refs": [],
        "tool_results": [],
    }


async def test_graph_executes_parallel_read_batch() -> None:
    memory_calls = 0

    async def memory_search(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        nonlocal memory_calls
        del context, arguments
        memory_calls += 1
        return ToolResult(ToolStatus.SUCCESS, "OK", "mem", data={"items": []})

    registry = ToolRegistry()
    register_search_tools(registry, SearchApplicationService(RecordingWebSearchAdapter()))
    registry.register(
        ToolDefinition(
            "memory.search",
            "memory",
            ToolRisk.READ,
            memory_search,
            required_arguments=("query",),
        )
    )
    graph = build_executive_graph(
        model_gateway=ParallelGateway(),
        tools=registry,
        checkpointer=InMemorySaver(),
    )
    state = initial_state()
    output: dict[str, Any] = await graph.ainvoke(
        state, {"configurable": {"thread_id": state["thread_id"]}}
    )

    assert memory_calls == 1
    assert output["final_response"].startswith("done:")
    tool_results = output.get("tool_results", [])
    assert any(item.get("tool_name") == "search.official" for item in tool_results)
    assert any(item.get("code") == "PARALLEL_BATCH_OK" for item in tool_results)
