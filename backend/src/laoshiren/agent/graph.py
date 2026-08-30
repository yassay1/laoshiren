import asyncio
from collections.abc import Awaitable, Callable
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
    ToolCallSpec,
    ToolStatus,
)
from laoshiren.agent.model_gateway import ExecutiveModelGateway
from laoshiren.agent.parallel import count_search_tools_in_results, validate_parallel_batch
from laoshiren.agent.policy import PolicyDecision, ToolPolicy
from laoshiren.agent.tools import (
    ToolExecutionContext,
    ToolRegistry,
    ToolReplayPolicy,
    build_tool_manifest,
)
from laoshiren.application.runtime.dto import ContextAssemblyRequestDTO
from laoshiren.application.runtime.ports import ModelContextAssembler

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
    payload: dict[str, Any] = {
        "kind": decision.kind.value,
        "content": decision.content,
        "tool_name": decision.tool_name,
        "tool_arguments": decision.tool_arguments,
        "prompt": decision.prompt,
    }
    if decision.tool_calls:
        payload["tool_calls"] = [
            {
                "tool_name": spec.tool_name,
                "tool_arguments": spec.tool_arguments,
            }
            for spec in decision.tool_calls
        ]
    return payload


def _tool_specs_from_decision(decision: dict[str, Any]) -> tuple[ToolCallSpec, ...]:
    raw_calls = decision.get("tool_calls")
    if not isinstance(raw_calls, list):
        return ()
    specs: list[ToolCallSpec] = []
    for item in raw_calls:
        if not isinstance(item, dict):
            continue
        tool_name = item.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name:
            continue
        arguments = item.get("tool_arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}
        specs.append(ToolCallSpec(tool_name=tool_name, tool_arguments=arguments))
    return tuple(specs)


def _with_tool_name(result: dict[str, Any], tool_name: str) -> dict[str, Any]:
    return {**result, "tool_name": tool_name}


def build_executive_graph(
    *,
    model_gateway: ExecutiveModelGateway,
    tools: ToolRegistry,
    checkpointer: BaseCheckpointSaver[Any],
    event_sink: AgentEventSink | None = None,
    policy_matrix: ToolPolicy | None = None,
    max_decisions: int = 12,
    max_tool_calls: int = 8,
    parallel_read_max: int = 4,
    search_max_per_run: int = 6,
    tool_ledger: ToolExecutionLedger | None = None,
    context_assembler: ModelContextAssembler | None = None,
    context_refresher: Callable[[GraphState], Awaitable[GraphState]] | None = None,
    max_input_tokens: int = 120_000,
    max_output_tokens: int = 16_000,
    max_external_actions: int = 3,
) -> CompiledStateGraph[GraphState, None, GraphState, GraphState]:
    """Build the deliberately small V1 Executive Graph."""

    sink = event_sink or NullAgentEventSink()
    tool_policy = policy_matrix or ToolPolicy(search_max_per_run=search_max_per_run)

    async def build_initial_context(state: GraphState) -> GraphState:
        return {
            "messages": list(state.get("messages", [])),
            "tool_results": list(state.get("tool_results", [])),
            "decision_count": state.get("decision_count", 0),
            "tool_call_count": state.get("tool_call_count", 0),
        }

    async def executive(state: GraphState) -> GraphState:
        if context_assembler is not None:
            raw_input_message_id = state.get("input_message_id")
            raw_source_refs = state.get("source_refs", [])
            source_refs = tuple(UUID(value) for value in raw_source_refs if isinstance(value, str))
            assembled = await context_assembler.assemble(
                request=ContextAssemblyRequestDTO(
                    user_id=UUID(state["user_id"]),
                    thread_id=UUID(state["thread_id"]),
                    run_id=UUID(state["run_id"]),
                    input_message_id=(
                        UUID(raw_input_message_id)
                        if isinstance(raw_input_message_id, str)
                        else None
                    ),
                    current_input=str(state.get("current_input", "")),
                    source_refs=source_refs,
                    decision_index=state.get("decision_count", 0),
                )
            )
            refreshed: GraphState = {
                "messages": assembled.messages,
                "prefetched_state": assembled.prefetched_state,
                "context_manifest": assembled.context_manifest,
            }
        else:
            refreshed = await context_refresher(state) if context_refresher is not None else {}
        invocation_state: GraphState = {**state, **refreshed}
        decision_count = state.get("decision_count", 0)
        budget = state.get("budget_snapshot", {})
        decision_limit = int(budget.get("max_model_steps", max_decisions))
        input_limit = int(budget.get("max_input_tokens", max_input_tokens))
        output_limit = int(budget.get("max_output_tokens", max_output_tokens))
        if decision_count >= decision_limit:
            raise AgentBudgetExceeded("Executive decision budget exceeded.")
        decision = await model_gateway.decide(
            state=invocation_state,
            available_tools=tools.names(),
            tool_manifest=build_tool_manifest(tools),
        )
        input_tokens_used = state.get("input_tokens_used", 0) + decision.input_tokens
        output_tokens_used = state.get("output_tokens_used", 0) + decision.output_tokens
        if input_tokens_used > input_limit or output_tokens_used > output_limit:
            raise AgentBudgetExceeded("Executive token budget exceeded.")
        route = {
            DecisionKind.RESPOND: "respond",
            DecisionKind.ASK_USER: "ask_user",
            DecisionKind.CALL_TOOL: "policy",
            DecisionKind.CALL_TOOLS: "parallel_policy",
        }[decision.kind]
        return {
            **refreshed,
            "decision": _decision_dict(decision),
            "route": cast(Any, route),
            "decision_count": decision_count + 1,
            "input_tokens_used": input_tokens_used,
            "output_tokens_used": output_tokens_used,
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
                "tool_name": name,
            }
            return {"tool_results": [*state.get("tool_results", []), result], "route": "executive"}
        arguments = decision.get("tool_arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}
        action_index = len(state.get("tool_results", []))
        action_id = str(uuid5(ACTION_NAMESPACE, f"{state['run_id']}:{action_index}:{name}"))
        pending = {
            "action_id": action_id,
            "tool_name": name,
            "arguments": arguments,
            "risk": definition.risk.value,
        }
        policy_result = tool_policy.evaluate(
            definition,
            state=dict(state),
            arguments=arguments,
        )
        if policy_result.decision is PolicyDecision.DENY:
            denied = {
                "status": ToolStatus.FAILED,
                "code": policy_result.code,
                "message": policy_result.message,
                "tool_name": name,
            }
            return {"tool_results": [*state.get("tool_results", []), denied], "route": "executive"}
        if policy_result.decision is PolicyDecision.REQUIRE_MORE_CONTEXT:
            blocked = {
                "status": ToolStatus.FAILED,
                "code": policy_result.code,
                "message": policy_result.message,
                "tool_name": name,
            }
            return {"tool_results": [*state.get("tool_results", []), blocked], "route": "executive"}
        if policy_result.decision is PolicyDecision.REQUIRE_CONFIRMATION:
            return {"pending_action": pending, "route": "confirmation"}
        return {"pending_action": pending, "route": "execute"}

    async def parallel_policy(state: GraphState) -> GraphState:
        specs = _tool_specs_from_decision(state["decision"])
        tool_results = list(state.get("tool_results", []))
        budget = state.get("budget_snapshot", {})
        tool_limit = int(budget.get("max_tool_actions", max_tool_calls))
        search_limit = int(budget.get("max_search_queries", search_max_per_run))
        validation = validate_parallel_batch(
            registry=tools,
            specs=specs,
            tool_call_count=state.get("tool_call_count", 0),
            max_tool_calls=tool_limit,
            parallel_read_max=parallel_read_max,
            search_count_in_run=count_search_tools_in_results(tool_results),
            search_max_per_run=search_limit,
        )
        if not validation.ok:
            blocked = {
                "status": ToolStatus.FAILED,
                "code": validation.code,
                "message": validation.message,
            }
            return {"tool_results": [*tool_results, blocked], "route": "executive"}

        pending_batch: list[dict[str, Any]] = []
        base_index = len(tool_results)
        for index, spec in enumerate(validation.specs):
            definition = tools.get(spec.tool_name)
            if definition is None:
                continue
            policy_result = tool_policy.evaluate(
                definition,
                state=dict(state),
                arguments=spec.tool_arguments,
            )
            if policy_result.decision is not PolicyDecision.ALLOW:
                blocked = {
                    "status": ToolStatus.FAILED,
                    "code": policy_result.code,
                    "message": policy_result.message,
                    "tool_name": spec.tool_name,
                }
                return {"tool_results": [*tool_results, blocked], "route": "executive"}
            action_id = str(
                uuid5(
                    ACTION_NAMESPACE,
                    f"{state['run_id']}:{base_index}:batch:{index}:{spec.tool_name}",
                )
            )
            pending_batch.append(
                {
                    "action_id": action_id,
                    "tool_name": spec.tool_name,
                    "arguments": spec.tool_arguments,
                }
            )
        return {"pending_batch": pending_batch, "route": "parallel_execute"}

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
            "tool_name": action.get("tool_name"),
        }
        return {
            "tool_results": [*state.get("tool_results", []), declined],
            "route": "executive",
        }

    async def _execute_one(
        *,
        state: GraphState,
        action_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        user_id = UUID(state["user_id"])
        run_id = UUID(state["run_id"])
        definition = tools.get(tool_name)
        replay_policy = (
            definition.replay_policy if definition is not None else ToolReplayPolicy.READ_ONLY
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
                return _with_tool_name(cached, tool_name)
            if not acquired:
                raise ToolExecutionBusy("Tool execution is owned by another worker.")
            claim_token_for = getattr(tool_ledger, "claim_token_for", None)
            if callable(claim_token_for):
                execution_context = ToolExecutionContext(
                    user_id=user_id,
                    run_id=run_id,
                    action_id=action_id,
                    tool_claim_owner=getattr(tool_ledger, "claim_owner", None),
                    tool_claim_token=claim_token_for(run_id=run_id, action_id=action_id),
                )
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
        result_data = _with_tool_name(result.as_dict(), tool_name)
        if tool_ledger is not None and result.ledger_receipt_persisted:
            acknowledge = getattr(tool_ledger, "acknowledge_atomic_completion", None)
            if callable(acknowledge):
                acknowledge(run_id=run_id, action_id=action_id)
        elif tool_ledger is not None:
            await tool_ledger.complete(
                user_id=user_id,
                run_id=run_id,
                action_id=action_id,
                result=result_data,
                succeeded=result.status in {ToolStatus.SUCCESS, ToolStatus.PARTIAL},
            )
        await sink.tool_finished(
            user_id=user_id,
            run_id=run_id,
            action_id=action_id,
            tool_name=tool_name,
            status=result.status,
            code=result.code,
        )
        return result_data

    async def execute(state: GraphState) -> GraphState:
        tool_call_count = state.get("tool_call_count", 0)
        budget = state.get("budget_snapshot", {})
        tool_limit = int(budget.get("max_tool_actions", max_tool_calls))
        external_limit = int(budget.get("max_external_actions", max_external_actions))
        if tool_call_count >= tool_limit:
            raise AgentBudgetExceeded("Executive tool-call budget exceeded.")
        action = state["pending_action"]
        definition = tools.get(str(action["tool_name"]))
        is_external = (
            definition is not None and definition.replay_policy is ToolReplayPolicy.NON_REPLAYABLE
        )
        external_action_count = state.get("external_action_count", 0)
        if is_external and external_action_count >= external_limit:
            raise AgentBudgetExceeded("Executive external-action budget exceeded.")
        arguments = action.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        result_data = await _execute_one(
            state=state,
            action_id=str(action["action_id"]),
            tool_name=str(action["tool_name"]),
            arguments=arguments,
        )
        return {
            "tool_results": [*state.get("tool_results", []), result_data],
            "route": "executive",
            "tool_call_count": tool_call_count + 1,
            "external_action_count": external_action_count + int(is_external),
        }

    async def parallel_execute(state: GraphState) -> GraphState:
        batch = state.get("pending_batch", [])
        if not isinstance(batch, list) or not batch:
            raise ValueError("Parallel execution requires a pending batch.")
        tool_call_count = state.get("tool_call_count", 0)
        budget = state.get("budget_snapshot", {})
        tool_limit = int(budget.get("max_tool_actions", max_tool_calls))
        external_limit = int(budget.get("max_external_actions", max_external_actions))
        if tool_call_count + len(batch) > tool_limit:
            raise AgentBudgetExceeded("Executive tool-call budget exceeded.")

        external_batch_count = 0
        for action in batch:
            definition = tools.get(str(action.get("tool_name", "")))
            if (
                definition is not None
                and definition.replay_policy is ToolReplayPolicy.NON_REPLAYABLE
            ):
                external_batch_count += 1
        external_action_count = state.get("external_action_count", 0)
        if external_action_count + external_batch_count > external_limit:
            raise AgentBudgetExceeded("Executive external-action budget exceeded.")

        async def run_action(action: dict[str, Any]) -> dict[str, Any]:
            arguments = action.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            return await _execute_one(
                state=state,
                action_id=str(action["action_id"]),
                tool_name=str(action["tool_name"]),
                arguments=arguments,
            )

        gathered = await asyncio.gather(
            *(run_action(item) for item in batch),
            return_exceptions=True,
        )
        batch_results: list[dict[str, Any]] = []
        for index, item in enumerate(gathered):
            action = batch[index]
            tool_name = str(action["tool_name"])
            if isinstance(item, BaseException):
                batch_results.append(
                    {
                        "status": ToolStatus.FAILED.value,
                        "code": "PARALLEL_TOOL_FAILED",
                        "message": str(item),
                        "tool_name": tool_name,
                    }
                )
            else:
                batch_results.append(item)

        combined = {
            "status": ToolStatus.SUCCESS.value,
            "code": "PARALLEL_BATCH_OK",
            "message": "Parallel read batch completed.",
            "batch_tool_names": [str(action["tool_name"]) for action in batch],
            "batch_results": batch_results,
        }
        return {
            "tool_results": [*state.get("tool_results", []), *batch_results, combined],
            "route": "executive",
            "tool_call_count": tool_call_count + len(batch),
            "external_action_count": external_action_count + external_batch_count,
        }

    graph = StateGraph(GraphState)
    graph.add_node("build_initial_context", build_initial_context)
    graph.add_node("executive", executive)
    graph.add_node("respond", respond)
    graph.add_node("ask_user", ask_user)
    graph.add_node("policy", policy)
    graph.add_node("parallel_policy", parallel_policy)
    graph.add_node("confirmation", confirmation)
    graph.add_node("execute", execute)
    graph.add_node("parallel_execute", parallel_execute)
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
        "parallel_policy",
        lambda state: state["route"],
        {"parallel_execute": "parallel_execute", "executive": "executive"},
    )
    graph.add_conditional_edges(
        "confirmation",
        lambda state: state["route"],
        {"execute": "execute", "executive": "executive"},
    )
    graph.add_edge("execute", "executive")
    graph.add_edge("parallel_execute", "executive")
    return graph.compile(checkpointer=checkpointer)
