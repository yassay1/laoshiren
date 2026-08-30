from typing import Any
from uuid import UUID, uuid4

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
    ToolReplayPolicy,
    ToolRisk,
)
from laoshiren.application.runtime.dto import ContextAssemblyDTO, ContextAssemblyRequestDTO

pytestmark = pytest.mark.asyncio


class RespondGateway:
    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
    ) -> ExecutiveDecision:
        assert available_tools == ()
        return ExecutiveDecision(DecisionKind.RESPOND, content=f"收到：{state['current_input']}")


class SensitiveToolGateway:
    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
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
        "run_claim_token": str(uuid4()),
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

    async def delete_tool(context: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        calls.append((context, arguments))
        return ToolResult(ToolStatus.SUCCESS, "OK", "Deleted.")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="test.delete",
            description="Test sensitive operation.",
            risk=ToolRisk.SENSITIVE_WRITE,
            handler=delete_tool,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
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

    resumed: dict[str, Any] = await graph.ainvoke(Command(resume={"action": "confirm"}), config)

    assert len(calls) == 1
    assert calls[0][1] == {"target": "demo"}
    assert resumed["final_response"] == "工具结果：SUCCESS"


async def test_graph_stops_repeated_decisions_at_budget() -> None:
    class LoopGateway:
        async def decide(
            self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
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


async def test_graph_enforces_normalized_token_budget() -> None:
    class Gateway:
        async def decide(self, **_: Any) -> ExecutiveDecision:
            return ExecutiveDecision(
                DecisionKind.RESPOND,
                content="too expensive",
                input_tokens=11,
                output_tokens=2,
            )

    state = initial_state()
    graph = build_executive_graph(
        model_gateway=Gateway(),
        tools=ToolRegistry(),
        checkpointer=InMemorySaver(),
        max_input_tokens=10,
    )
    with pytest.raises(AgentBudgetExceeded, match="token budget"):
        await graph.ainvoke(state, {"configurable": {"thread_id": state["run_id"]}})


async def test_context_is_reassembled_before_every_model_invocation() -> None:
    refresh_count = 0
    observed: list[int] = []

    async def refresh(state: GraphState) -> GraphState:
        nonlocal refresh_count
        refresh_count += 1
        return {
            "prefetched_state": {"authoritative_revision": refresh_count},
            "context_manifest": {"decision_index": state.get("decision_count", 0)},
        }

    class Gateway:
        async def decide(
            self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
        ) -> ExecutiveDecision:
            del available_tools, tool_manifest
            observed.append(int(state["prefetched_state"]["authoritative_revision"]))
            if len(observed) == 1:
                return ExecutiveDecision(DecisionKind.CALL_TOOL, tool_name="missing")
            return ExecutiveDecision(DecisionKind.RESPOND, content="fresh")

    state = initial_state()
    graph = build_executive_graph(
        model_gateway=Gateway(),
        tools=ToolRegistry(),
        checkpointer=InMemorySaver(),
        context_refresher=refresh,
    )
    output = await graph.ainvoke(state, {"configurable": {"thread_id": state["run_id"]}})
    assert output["final_response"] == "fresh"
    assert observed == [1, 2]


async def test_graph_uses_application_context_assembler_with_stable_references() -> None:
    requests: list[ContextAssemblyRequestDTO] = []

    class Assembler:
        async def assemble(self, *, request: ContextAssemblyRequestDTO) -> ContextAssemblyDTO:
            requests.append(request)
            return ContextAssemblyDTO(
                messages=[],
                prefetched_state={"state_authority": "PERSONAL_STATE"},
                context_manifest={"decision_index": request.decision_index},
            )

    class Gateway:
        async def decide(
            self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
        ) -> ExecutiveDecision:
            del available_tools, tool_manifest
            assert state["prefetched_state"]["state_authority"] == "PERSONAL_STATE"
            return ExecutiveDecision(DecisionKind.RESPOND, content="assembled")

    state = initial_state()
    output = await build_executive_graph(
        model_gateway=Gateway(),
        tools=ToolRegistry(),
        checkpointer=InMemorySaver(),
        context_assembler=Assembler(),
    ).ainvoke(state, {"configurable": {"thread_id": state["run_id"]}})

    assert output["final_response"] == "assembled"
    assert len(requests) == 1
    assert requests[0].run_id == UUID(state["run_id"])
    assert requests[0].decision_index == 0


async def test_graph_reuses_durable_cached_tool_result_without_handler_replay() -> None:
    handler_calls = 0

    async def handler(context: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        nonlocal handler_calls
        del context, arguments
        handler_calls += 1
        return ToolResult(ToolStatus.SUCCESS, "UNEXPECTED", "should not execute")

    class Gateway:
        async def decide(
            self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
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
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
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


async def test_partial_tool_result_is_a_successful_ledger_receipt() -> None:
    completions: list[dict[str, Any]] = []

    class Gateway:
        async def decide(self, *, state: GraphState, **_: Any) -> ExecutiveDecision:
            if state.get("tool_results"):
                return ExecutiveDecision(DecisionKind.RESPOND, content="partial retained")
            return ExecutiveDecision(DecisionKind.CALL_TOOL, tool_name="test.partial")

    async def handler(_: ToolExecutionContext, __: dict[str, Any]) -> ToolResult:
        return ToolResult(ToolStatus.PARTIAL, "PARTIAL_OK", "partial", warnings=("late",))

    class Ledger:
        async def claim(self, **_: Any) -> tuple[bool, dict[str, Any] | None]:
            return True, None

        async def complete(self, **values: Any) -> None:
            completions.append(values)

    registry = ToolRegistry()
    registry.register(ToolDefinition("test.partial", "partial", ToolRisk.READ, handler))
    state = initial_state()
    output = await build_executive_graph(
        model_gateway=Gateway(),
        tools=registry,
        checkpointer=InMemorySaver(),
        tool_ledger=Ledger(),
    ).ainvoke(state, {"configurable": {"thread_id": state["run_id"]}})

    assert output["final_response"] == "partial retained"
    assert completions[0]["succeeded"] is True
    assert completions[0]["result"]["receipt"]["code"] == "PARTIAL_OK"


async def test_checkpointed_tool_action_resumes_without_rethinking_model_step() -> None:
    gateway_calls = 0
    handler_calls = 0

    class Gateway:
        async def decide(self, *, state: GraphState, **_: Any) -> ExecutiveDecision:
            nonlocal gateway_calls
            gateway_calls += 1
            if state.get("tool_results"):
                return ExecutiveDecision(DecisionKind.RESPOND, content="done")
            return ExecutiveDecision(DecisionKind.CALL_TOOL, tool_name="test.crash")

    async def handler(_: ToolExecutionContext, __: dict[str, Any]) -> ToolResult:
        nonlocal handler_calls
        handler_calls += 1
        if handler_calls == 1:
            raise RuntimeError("injected crash after accepted model step")
        return ToolResult(ToolStatus.SUCCESS, "RECOVERED", "recovered")

    registry = ToolRegistry()
    registry.register(ToolDefinition("test.crash", "crash once", ToolRisk.READ, handler))
    state = initial_state()
    graph = build_executive_graph(
        model_gateway=Gateway(), tools=registry, checkpointer=InMemorySaver()
    )
    config: RunnableConfig = {"configurable": {"thread_id": state["run_id"]}}
    with pytest.raises(RuntimeError, match="injected crash"):
        await graph.ainvoke(state, config, durability="sync")
    output = await graph.ainvoke(None, config, durability="sync")
    assert output["final_response"] == "done"
    assert handler_calls == 2
    assert gateway_calls == 2
