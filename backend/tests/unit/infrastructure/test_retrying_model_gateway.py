from typing import Any

import pytest

from laoshiren.agent.contracts import DecisionKind, ExecutiveDecision, GraphState
from laoshiren.agent.model_gateway import ModelGatewayError
from laoshiren.infrastructure.ai.retrying import RetryingExecutiveModelGateway


class Gateway:
    def __init__(self, failures: list[ModelGatewayError]) -> None:
        self.failures = failures
        self.calls = 0

    async def decide(self, **_: Any) -> ExecutiveDecision:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return ExecutiveDecision(DecisionKind.RESPOND, content="ok")


@pytest.mark.asyncio
async def test_retryable_provider_failure_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("laoshiren.infrastructure.ai.retrying.asyncio.sleep", no_sleep)
    inner = Gateway(
        [
            ModelGatewayError("MODEL_PROVIDER_UNAVAILABLE", "503", retryable=True),
            ModelGatewayError("MODEL_PROVIDER_UNAVAILABLE", "429", retryable=True),
        ]
    )
    gateway = RetryingExecutiveModelGateway(inner, max_attempts=3, base_seconds=0)
    result = await gateway.decide(state=GraphState(), available_tools=(), tool_manifest="")
    assert result.content == "ok"
    assert inner.calls == 3


@pytest.mark.asyncio
async def test_non_retryable_provider_failure_is_not_replayed() -> None:
    inner = Gateway([ModelGatewayError("MODEL_AUTH_FAILED", "401", retryable=False)])
    gateway = RetryingExecutiveModelGateway(inner, max_attempts=3, base_seconds=0)
    with pytest.raises(ModelGatewayError, match="401"):
        await gateway.decide(state=GraphState(), available_tools=(), tool_manifest="")
    assert inner.calls == 1
