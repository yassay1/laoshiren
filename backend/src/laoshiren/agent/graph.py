from typing import Any, Protocol, cast
from uuid import UUID, uuid5

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from laoshiren.agent.contracts import (
    AgentBudgetExceeded,
    DecisionKind,
    ExecutiveDecision,
    GraphState,
    ToolStatus,
)
from laoshiren.agent.model_gateway import ExecutiveModelGateway
from laoshiren.agent.policy import PolicyDecision, ToolPolicy
from laoshiren.agent.tools import ToolExecutionContext, ToolRegistry, ToolReplayPolicy

ACTION_NAMESPACE = UUID("af195d42-065c-4a50-9eb3-6ea8e46b1928")


class AgentEventSink(Protocol):
    async def tool_started(
        self, *, user_id: UUID, run_id: UUID, action_id: str, tool_name: str
    ) -> None: ...

    async def tool_finished(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        action_id: str,
        tool_name: str,
        status: ToolStatus,
        code: str,
    ) -> None: ...


class ToolExecutionLedger(Protocol):
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
    ) -> tuple[bool, dict[str, Any] | None]: ...

    async def complete(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        action_id: str,
        result: dict[str, Any],
        succeeded: bool,
    ) -> None: ...


class ToolExecutionBusy(RuntimeError):
    """Another worker still owns this durable Tool action."""


class ToolOutcomeUnknown(RuntimeError):
    """A non-replayable Tool lost its lease after its outcome became unknowable."""


class NullAgentEventSink:
    async def tool_started(
        self, *, user_id: UUID, run_id: UUID, action_id: str, tool_name: str
    ) -> None:
        return None

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
        return None


def _decision_dict(decision: ExecutiveDecision) -> dict[str, Any]:
    return {
        "kind": decision.kind.value,
        "content": decision.content,
        "tool_name": decision.tool_name,
        "tool_arguments": decision.tool_arguments,
        "prompt": decision.prompt,
    }


def build_executive_graph(
    *,
    model_gateway: ExecutiveModelGateway,
    tools: ToolRegistry,
    checkpointer: BaseCheckpointSaver[Any],
    event_sink: AgentEventSink | None = None,
    policy_matrix: ToolPolicy | None = None,
    max_decisions: int = 12,
    max_tool_calls: int = 8,
    tool_ledger: ToolExecutionLedger | None = None,
) -> CompiledStateGraph[GraphState, None, GraphState, GraphState]:
    """Build the deliberately small V1 Executive Graph."""

    sink = event_sink or NullAgentEventSink()
    tool_policy = policy_matrix or ToolPolicy()

    async def build_initial_context(state: GraphState) -> GraphState:
        return {
            "messages": list(state.get("messages", [])),
            "tool_results": list(state.get("tool_results", [])),
            "decision_count": state.get("decision_count", 0),
            "tool_call_count": state.get("tool_call_count", 0),
        }

    async def executive(state: GraphState) -> GraphState:
        decision_count = state.get("decision_count", 0)
        if decision_count >= max_decisions:
            raise AgentBudgetExceeded("Executive decision budget exceeded.")
        decision = await model_gateway.decide(state=state, available_tools=tools.names())
        route = {
            DecisionKind.RESPOND: "respond",
            DecisionKind.ASK_USER: "ask_user",
            DecisionKind.CALL_TOOL: "policy",
        }[decision.kind]
        return {
            "decision": _decision_dict(decision),
            "route": cast(Any, route),
            "decision_count": decision_count + 1,
        }

    async def respond(state: GraphState) -> GraphState:
        content = state["decision"].get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Executive response must contain text.")
        return {"final_response": content.strip()}

    async def ask_user(state: GraphState) -> GraphState:
        prompt = state["decision"].get("prompt")
        if not isinstance(prompt, dict):
            raise ValueError("Executive interrupt payload must be an object.")
        response = interrupt(prompt)
        if not isinstance(response, dict):
            response = {"value": response}
        return {"user_response": response, "route": "executive"}

    async def policy(state: GraphState) -> GraphState:
        decision = state["decision"]
        name = decision.get("tool_name")
        if not isinstance(name, str):
            raise ValueError("Tool decision is missing its name.")
        definition = tools.get(name)
        if definition is None:
            result = {
                "status": ToolStatus.NOT_FOUND,
                "code": "TOOL_NOT_FOUND",
                "message": "Tool is unavailable.",
            }
            return {"tool_results": [*state.get("tool_results", []), result], "route": "executive"}
        action_index = len(state.get("tool_results", []))
        action_id = str(uuid5(ACTION_NAMESPACE, f"{state['run_id']}:{action_index}:{name}"))
        pending = {
            "action_id": action_id,
            "tool_name": name,
            "arguments": decision.get("tool_arguments", {}),
            "risk": definition.risk.value,
        }
        policy_result = tool_policy.evaluate(definition)
        if policy_result.decision is PolicyDecision.DENY:
            denied = {
                "status": ToolStatus.FAILED,
                "code": policy_result.code,
                "message": policy_result.message,
            }
            return {"tool_results": [*state.get("tool_results", []), denied], "route": "executive"}
        if policy_result.decision is PolicyDecision.REQUIRE_CONFIRMATION:
            return {"pending_action": pending, "route": "confirmation"}
        return {"pending_action": pending, "route": "execute"}

    async def confirmation(state: GraphState) -> GraphState:
        action = state["pending_action"]
        response = interrupt(
            {
                "type": "confirmation",
                "title": "确认执行敏感操作",
                "message": f"是否允许执行 {action['tool_name']}？",
                "action_id": action["action_id"],
                "options": [
                    {"id": "confirm", "label": "确认"},
                    {"id": "cancel", "label": "取消"},
                ],
            }
        )
        if isinstance(response, dict) and response.get("action") == "confirm":
            return {"route": "execute"}
        declined = {
            "status": ToolStatus.REQUIRES_CONFIRMATION,
            "code": "USER_DECLINED",
            "message": "User declined the sensitive action.",
        }
        return {
            "tool_results": [*state.get("tool_results", []), declined],
            "route": "executive",
        }

    async def execute(state: GraphState) -> GraphState:
        tool_call_count = state.get("tool_call_count", 0)
        if tool_call_count >= max_tool_calls:
            raise AgentBudgetExceeded("Executive tool-call budget exceeded.")
        action = state["pending_action"]
        arguments = action.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        user_id = UUID(state["user_id"])
        run_id = UUID(state["run_id"])
        action_id = str(action["action_id"])
        tool_name = str(action["tool_name"])
        definition = tools.get(tool_name)
        replay_policy = (
            definition.replay_policy
            if definition is not None
            else ToolReplayPolicy.READ_ONLY
        )
        execution_context = ToolExecutionContext(
            user_id=user_id,
            run_id=run_id,
            action_id=action_id,
        )
        if tool_ledger is not None:
            acquired, cached = await tool_ledger.claim(
                user_id=user_id,
                run_id=run_id,
                run_claim_token=UUID(state["run_claim_token"]),
                action_id=action_id,
                tool_name=tool_name,
                arguments=arguments,
                replay_policy=replay_policy,
                idempotency_key=execution_context.idempotency_key,
            )
            if cached is not None:
                return {
                    "tool_results": [*state.get("tool_results", []), cached],
                    "route": "executive",
                    "tool_call_count": tool_call_count + 1,
                }
            if not acquired:
                raise ToolExecutionBusy("Tool execution is owned by another worker.")
        await sink.tool_started(
            user_id=user_id,
            run_id=run_id,
            action_id=action_id,
            tool_name=tool_name,
        )
        result = await tools.execute(
            name=tool_name,
            context=execution_context,
            arguments=arguments,
        )
        result_data = result.as_dict()
        if tool_ledger is not None:
            await tool_ledger.complete(
                user_id=user_id,
                run_id=run_id,
                action_id=action_id,
                result=result_data,
                succeeded=result.status is ToolStatus.SUCCESS,
            )
        await sink.tool_finished(
            user_id=user_id,
            run_id=run_id,
            action_id=action_id,
            tool_name=tool_name,
            status=result.status,
            code=result.code,
        )
        return {
            "tool_results": [*state.get("tool_results", []), result_data],
            "route": "executive",
            "tool_call_count": tool_call_count + 1,
        }

    graph = StateGraph(GraphState)
    graph.add_node("build_initial_context", build_initial_context)
    graph.add_node("executive", executive)
    graph.add_node("respond", respond)
    graph.add_node("ask_user", ask_user)
    graph.add_node("policy", policy)
    graph.add_node("confirmation", confirmation)
    graph.add_node("execute", execute)
    graph.add_edge(START, "build_initial_context")
    graph.add_edge("build_initial_context", "executive")
    graph.add_conditional_edges("executive", lambda state: state["route"])
    graph.add_edge("respond", END)
    graph.add_edge("ask_user", "executive")
    graph.add_conditional_edges(
        "policy",
        lambda state: state["route"],
        {
            "confirmation": "confirmation",
            "execute": "execute",
            "executive": "executive",
        },
    )
    graph.add_conditional_edges(
        "confirmation",
        lambda state: state["route"],
        {"execute": "execute", "executive": "executive"},
    )
    graph.add_edge("execute", "executive")
    return graph.compile(checkpointer=checkpointer)
