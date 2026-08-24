from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, TypedDict


class DecisionKind(StrEnum):
    RESPOND = "respond"
    ASK_USER = "ask_user"
    CALL_TOOL = "call_tool"


@dataclass(frozen=True, slots=True)
class ExecutiveDecision:
    kind: DecisionKind
    content: str | None = None
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    prompt: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.kind is DecisionKind.RESPOND and not self.content:
            raise ValueError("A response decision requires content.")
        if self.kind is DecisionKind.ASK_USER and self.prompt is None:
            raise ValueError("An ask-user decision requires a prompt.")
        if self.kind is DecisionKind.CALL_TOOL and not self.tool_name:
            raise ValueError("A tool decision requires a tool name.")


class ToolStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    REQUIRES_CONFIRMATION = "REQUIRES_CONFIRMATION"
    REQUIRES_USER_INPUT = "REQUIRES_USER_INPUT"


@dataclass(frozen=True, slots=True)
class ToolResult:
    status: ToolStatus
    code: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    retryable: bool = False
    mutation_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "code": self.code,
            "message": self.message,
            "data": self.data,
            "retryable": self.retryable,
            "mutation_refs": list(self.mutation_refs),
            "source_refs": list(self.source_refs),
        }


class GraphState(TypedDict, total=False):
    user_id: str
    thread_id: str
    run_id: str
    run_claim_token: str
    current_input: str
    messages: list[dict[str, Any]]
    source_refs: list[str]
    prefetched_state: dict[str, Any]
    tool_results: list[dict[str, Any]]
    decision: dict[str, Any]
    pending_action: dict[str, Any]
    user_response: dict[str, Any]
    final_response: str
    decision_count: int
    tool_call_count: int
    route: Literal[
        "respond", "ask_user", "policy", "confirmation", "execute", "executive"
    ]


class AgentBudgetExceeded(RuntimeError):
    """Raised when one Run exceeds a deterministic execution guardrail."""
