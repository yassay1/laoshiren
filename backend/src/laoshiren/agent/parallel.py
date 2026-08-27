import json
from dataclasses import dataclass
from typing import Any

from laoshiren.agent.contracts import DecisionKind, ExecutiveDecision, ToolCallSpec
from laoshiren.agent.model_gateway import ModelGatewayError
from laoshiren.agent.tools import ToolRegistry, ToolRisk


@dataclass(frozen=True, slots=True)
class ParallelBatchValidation:
    ok: bool
    code: str
    message: str
    specs: tuple[ToolCallSpec, ...] = ()


def canonicalize_arguments(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)


def validate_parallel_batch(
    *,
    registry: ToolRegistry,
    specs: tuple[ToolCallSpec, ...],
    tool_call_count: int,
    max_tool_calls: int,
    parallel_read_max: int,
    search_count_in_run: int,
    search_max_per_run: int,
) -> ParallelBatchValidation:
    if not specs:
        return ParallelBatchValidation(
            False, "PARALLEL_BATCH_EMPTY", "Parallel batch must include at least one tool."
        )
    if len(specs) > parallel_read_max:
        return ParallelBatchValidation(
            False,
            "PARALLEL_BATCH_TOO_LARGE",
            f"Parallel batch exceeds the limit of {parallel_read_max} tools.",
        )
    if tool_call_count + len(specs) > max_tool_calls:
        return ParallelBatchValidation(
            False,
            "TOOL_BUDGET_EXCEEDED",
            "Parallel batch would exceed the tool-call budget for this run.",
        )

    search_in_batch = 0
    unique: list[ToolCallSpec] = []
    seen_keys: set[tuple[str, str]] = set()
    for spec in specs:
        definition = registry.get(spec.tool_name)
        if definition is None:
            return ParallelBatchValidation(
                False,
                "TOOL_NOT_FOUND",
                f"Tool is unavailable: {spec.tool_name}",
            )
        if definition.risk is not ToolRisk.READ:
            return ParallelBatchValidation(
                False,
                "PARALLEL_WRITE_FORBIDDEN",
                "Parallel batches may only include read-only tools.",
            )
        key = (spec.tool_name, canonicalize_arguments(spec.tool_arguments))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique.append(spec)
        if spec.tool_name.startswith("search."):
            search_in_batch += 1

    if search_in_batch > 2:
        return ParallelBatchValidation(
            False,
            "SEARCH_BATCH_LIMIT",
            "Parallel batch may include at most two search tools.",
        )
    if search_count_in_run + search_in_batch > search_max_per_run:
        return ParallelBatchValidation(
            False,
            "SEARCH_QUOTA_EXCEEDED",
            "Search quota for this run has been exceeded.",
        )

    return ParallelBatchValidation(True, "OK", "Parallel batch is valid.", tuple(unique))


def count_search_tools_in_results(tool_results: list[dict[str, Any]]) -> int:
    count = 0
    for result in tool_results:
        tool_name = result.get("tool_name")
        if isinstance(tool_name, str) and tool_name.startswith("search."):
            count += 1
            continue
        names = result.get("batch_tool_names")
        if isinstance(names, list):
            count += sum(
                1 for name in names if isinstance(name, str) and name.startswith("search.")
            )
    return count


def parse_executive_decision(
    value: Any, *, available_tools: tuple[str, ...]
) -> ExecutiveDecision:
    if not isinstance(value, dict):
        raise ModelGatewayError(
            "MODEL_INVALID_RESPONSE", "Model decision must be an object.", retryable=True
        )
    try:
        kind = DecisionKind(str(value["kind"]))
    except (KeyError, ValueError) as exc:
        raise ModelGatewayError(
            "MODEL_INVALID_RESPONSE", "Model decision kind is invalid.", retryable=True
        ) from exc
    if kind is DecisionKind.RESPOND:
        return ExecutiveDecision(kind, content=str(value.get("content", "")).strip())
    if kind is DecisionKind.ASK_USER:
        prompt = value.get("prompt")
        if not isinstance(prompt, dict):
            raise ModelGatewayError(
                "MODEL_INVALID_RESPONSE",
                "Model ask-user prompt must be an object.",
                retryable=True,
            )
        return ExecutiveDecision(kind, prompt=prompt)
    if kind is DecisionKind.CALL_TOOLS:
        raw_tools = value.get("tools")
        if not isinstance(raw_tools, list) or not raw_tools:
            raise ModelGatewayError(
                "MODEL_INVALID_RESPONSE",
                "Parallel tool decision must include a non-empty tools array.",
                retryable=True,
            )
        specs: list[ToolCallSpec] = []
        for item in raw_tools:
            if not isinstance(item, dict):
                raise ModelGatewayError(
                    "MODEL_INVALID_RESPONSE",
                    "Each parallel tool entry must be an object.",
                    retryable=True,
                )
            tool_name = str(item.get("tool_name", ""))
            if tool_name not in available_tools:
                raise ModelGatewayError(
                    "MODEL_INVALID_RESPONSE",
                    "Model selected an unavailable tool.",
                    retryable=True,
                )
            arguments = item.get("tool_arguments", {})
            if not isinstance(arguments, dict):
                raise ModelGatewayError(
                    "MODEL_INVALID_RESPONSE",
                    "Model tool arguments must be an object.",
                    retryable=True,
                )
            specs.append(ToolCallSpec(tool_name=tool_name, tool_arguments=arguments))
        return ExecutiveDecision(kind, tool_calls=tuple(specs))
    tool_name = str(value.get("tool_name", ""))
    if tool_name not in available_tools:
        raise ModelGatewayError(
            "MODEL_INVALID_RESPONSE",
            "Model selected an unavailable tool.",
            retryable=True,
        )
    arguments = value.get("tool_arguments", {})
    if not isinstance(arguments, dict):
        raise ModelGatewayError(
            "MODEL_INVALID_RESPONSE",
            "Model tool arguments must be an object.",
            retryable=True,
        )
    return ExecutiveDecision(kind, tool_name=tool_name, tool_arguments=arguments)
