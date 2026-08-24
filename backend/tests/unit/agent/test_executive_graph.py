from typing import Any
from uuid import uuid4

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from laoshiren.agent.contracts import (
    AgentBudgetExceeded,
    DecisionKind,
    ExecutiveDecision,
    GraphState,
    ToolResult,
    ToolStatus,
)
from laoshiren.agent.graph import build_executive_graph
from laoshiren.agent.tools import (
    ToolDefinition,
    ToolExecutionContext,
    ToolRegistry,
    ToolRisk,
)

pytestmark = pytest.mark.asyncio


class RespondGateway:
    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...]
    ) -> ExecutiveDecision:
        assert available_tools == ()
        return ExecutiveDecision(DecisionKind.RESPOND, content=f"收到：{state['current_input']}")


class SensitiveToolGateway:
    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...]
    ) -> ExecutiveDecision:
        assert available_tools == ("test.delete",)
        if state.get("tool_results"):
            result = state["tool_results"][-1]
            return ExecutiveDecision(
                DecisionKind.RESPOND,
                content=f"工具结果：{result['status']}",
            )
        return ExecutiveDecision(
            DecisionKind.CALL_TOOL,
            tool_name="test.delete",
            tool_arguments={"target": "demo"},
        )


def initial_state() -> GraphState:
    return {
        "user_id": str(uuid4()),
        "thread_id": str(uuid4()),
        "run_id": str(uuid4()),
        "current_input": "处理这件事",
        "messages": [],
        "source_refs": [],
        "tool_results": [],
    }


async def test_graph_returns_executive_response() -> None:
    state = initial_state()
    graph = build_executive_graph(
        model_gateway=RespondGateway(), tools=ToolRegistry(), checkpointer=InMemorySaver()
    )
    config: RunnableConfig = {"configurable": {"thread_id": state["thread_id"]}}

    output: dict[str, Any] = await graph.ainvoke(state, config)

    assert output["final_response"] == "收到：处理这件事"


async def test_sensitive_tool_interrupts_and_resumes_after_confirmation() -> None:
    calls: list[tuple[ToolExecutionContext, dict[str, Any]]] = []

    async def delete_tool(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        calls.append((context, arguments))
        return ToolResult(ToolStatus.SUCCESS, "OK", "Deleted.")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="test.delete",
            description="Test sensitive operation.",
            risk=ToolRisk.SENSITIVE_WRITE,
            handler=delete_tool,
        )
    )
    state = initial_state()
    graph = build_executive_graph(
        model_gateway=SensitiveToolGateway(),
        tools=registry,
        checkpointer=InMemorySaver(),
    )
    config: RunnableConfig = {"configurable": {"thread_id": state["thread_id"]}}

    interrupted: dict[str, Any] = await graph.ainvoke(state, config)

    assert calls == []
    assert interrupted["__interrupt__"][0].value["type"] == "confirmation"

    resumed: dict[str, Any] = await graph.ainvoke(
        Command(resume={"action": "confirm"}), config
    )

    assert len(calls) == 1
    assert calls[0][1] == {"target": "demo"}
    assert resumed["final_response"] == "工具结果：SUCCESS"


async def test_graph_stops_repeated_decisions_at_budget() -> None:
    class LoopGateway:
        async def decide(
            self, *, state: GraphState, available_tools: tuple[str, ...]
        ) -> ExecutiveDecision:
            del state, available_tools
            return ExecutiveDecision(DecisionKind.CALL_TOOL, tool_name="missing")

    state = initial_state()
    graph = build_executive_graph(
        model_gateway=LoopGateway(),
        tools=ToolRegistry(),
        checkpointer=InMemorySaver(),
        max_decisions=2,
    )
    config: RunnableConfig = {"configurable": {"thread_id": state["run_id"]}}

    with pytest.raises(AgentBudgetExceeded):
        await graph.ainvoke(state, config)


async def test_graph_reuses_durable_cached_tool_result_without_handler_replay() -> None:
    handler_calls = 0

    async def handler(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        nonlocal handler_calls
        del context, arguments
        handler_calls += 1
        return ToolResult(ToolStatus.SUCCESS, "UNEXPECTED", "should not execute")

    class Gateway:
        async def decide(
            self, *, state: GraphState, available_tools: tuple[str, ...]
        ) -> ExecutiveDecision:
            del available_tools
            if state.get("tool_results"):
                return ExecutiveDecision(
                    DecisionKind.RESPOND,
                    content=state["tool_results"][-1]["code"],
                )
            return ExecutiveDecision(
                DecisionKind.CALL_TOOL,
                tool_name="test.cached",
                tool_arguments={"value": 1},
            )

    class CachedLedger:
        async def claim(self, **values: Any) -> tuple[bool, dict[str, Any] | None]:
            del values
            return False, {
                "status": "SUCCESS",
                "code": "CACHED",
                "message": "cached result",
                "data": {},
            }

        async def complete(self, **values: Any) -> None:
            raise AssertionError(f"cached execution completed again: {values}")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            "test.cached",
            "cached tool",
            ToolRisk.REVERSIBLE_WRITE,
            handler,
        )
    )
    state = initial_state()
    graph = build_executive_graph(
        model_gateway=Gateway(),
        tools=registry,
        checkpointer=InMemorySaver(),
        tool_ledger=CachedLedger(),
    )

    output: dict[str, Any] = await graph.ainvoke(
        state, {"configurable": {"thread_id": state["run_id"]}}
    )

    assert output["final_response"] == "CACHED"
    assert handler_calls == 0
