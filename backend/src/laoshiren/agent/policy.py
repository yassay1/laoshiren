from dataclasses import dataclass
from enum import StrEnum

from laoshiren.agent.tools import ToolDefinition, ToolRisk


class PolicyDecision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"


@dataclass(frozen=True, slots=True)
class PolicyResult:
    decision: PolicyDecision
    code: str
    message: str


class ToolPolicy:
    """Deterministic V1 policy matrix; prompts never override this decision."""

    def evaluate(self, definition: ToolDefinition) -> PolicyResult:
        if not definition.enabled:
            return PolicyResult(PolicyDecision.DENY, "TOOL_DISABLED", "Tool is disabled.")
        if definition.risk in {ToolRisk.SENSITIVE_WRITE, ToolRisk.IRREVERSIBLE}:
            return PolicyResult(
                PolicyDecision.REQUIRE_CONFIRMATION,
                "CONFIRMATION_REQUIRED",
                "Explicit user confirmation is required.",
            )
        return PolicyResult(PolicyDecision.ALLOW, "ALLOWED", "Tool execution is allowed.")
