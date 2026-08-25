from typing import Protocol

from laoshiren.agent.contracts import ExecutiveDecision, GraphState


class ModelGatewayError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ExecutiveModelGateway(Protocol):
    """Provider-neutral boundary for the single Executive Agent."""

    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
    ) -> ExecutiveDecision: ...
