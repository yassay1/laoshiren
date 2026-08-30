import asyncio
import random

from laoshiren.agent.contracts import ExecutiveDecision, GraphState
from laoshiren.agent.model_gateway import ExecutiveModelGateway, ModelGatewayError


class FailoverExecutiveModelGateway:
    """Try an optional secondary provider before Runtime retry is exhausted."""

    def __init__(
        self,
        primary: ExecutiveModelGateway,
        secondary: ExecutiveModelGateway | None = None,
    ) -> None:
        self._primary = primary
        self._secondary = secondary

    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
    ) -> ExecutiveDecision:
        try:
            return await self._primary.decide(
                state=state,
                available_tools=available_tools,
                tool_manifest=tool_manifest,
            )
        except ModelGatewayError as error:
            # Only retryable provider failures may fail over. Auth, quota,
            # invalid request and other permanent errors remain authoritative.
            if self._secondary is None or not error.retryable:
                raise
            return await self._secondary.decide(
                state=state,
                available_tools=available_tools,
                tool_manifest=tool_manifest,
            )


class RetryingExecutiveModelGateway:
    """Bounded Runtime retry; provider SDK retries remain disabled."""

    def __init__(
        self,
        inner: ExecutiveModelGateway,
        *,
        max_attempts: int = 3,
        base_seconds: float = 0.25,
    ) -> None:
        if max_attempts <= 0 or base_seconds < 0:
            raise ValueError("Model retry settings are invalid.")
        self._inner = inner
        self._max_attempts = max_attempts
        self._base_seconds = base_seconds

    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
    ) -> ExecutiveDecision:
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await self._inner.decide(
                    state=state,
                    available_tools=available_tools,
                    tool_manifest=tool_manifest,
                )
            except ModelGatewayError as error:
                if not error.retryable or attempt == self._max_attempts:
                    raise
                delay = self._base_seconds * (2 ** (attempt - 1))
                await asyncio.sleep(delay * random.uniform(0.8, 1.2))
        raise RuntimeError("Unreachable model retry state.")
