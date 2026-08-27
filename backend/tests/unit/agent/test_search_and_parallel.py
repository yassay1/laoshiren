from uuid import uuid4

import pytest

from laoshiren.agent.contracts import DecisionKind, ToolCallSpec, ToolStatus
from laoshiren.agent.parallel import parse_executive_decision, validate_parallel_batch
from laoshiren.agent.policy import PolicyDecision, ToolPolicy
from laoshiren.agent.tools import (
    ToolDefinition,
    ToolExecutionContext,
    ToolRegistry,
    ToolReplayPolicy,
    ToolRisk,
    register_search_tools,
)
from laoshiren.application.search.service import SearchApplicationService
from laoshiren.infrastructure.search.recording import RecordingWebSearchAdapter


async def _unused_handler(
    context: ToolExecutionContext, arguments: dict[str, object]
) -> object:
    raise AssertionError((context, arguments))


def test_parse_call_tools_decision() -> None:
    decision = parse_executive_decision(
        {
            "kind": "call_tools",
            "tools": [
                {"tool_name": "search.web", "tool_arguments": {"query": "demo"}},
                {"tool_name": "memory.search", "tool_arguments": {"query": "prefs"}},
            ],
        },
        available_tools=("search.web", "memory.search"),
    )
    assert decision.kind is DecisionKind.CALL_TOOLS
    assert len(decision.tool_calls) == 2
    assert decision.tool_calls[0].tool_name == "search.web"


def test_parallel_batch_rejects_write_tools() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition("state.get_thing", "read", ToolRisk.READ, _unused_handler)
    )
    registry.register(
        ToolDefinition(
            "state.create_thing",
            "write",
            ToolRisk.REVERSIBLE_WRITE,
            _unused_handler,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
        )
    )
    validation = validate_parallel_batch(
        registry=registry,
        specs=(
            ToolCallSpec("state.get_thing", {"thing_id": str(uuid4())}),
            ToolCallSpec("state.create_thing", {"name": "x"}),
        ),
        tool_call_count=0,
        max_tool_calls=8,
        parallel_read_max=4,
        search_count_in_run=0,
        search_max_per_run=6,
    )
    assert not validation.ok
    assert validation.code == "PARALLEL_WRITE_FORBIDDEN"


@pytest.mark.asyncio
async def test_search_tools_return_structured_hits() -> None:
    registry = ToolRegistry()
    service = SearchApplicationService(RecordingWebSearchAdapter())
    register_search_tools(registry, service)
    context = ToolExecutionContext(user_id=uuid4(), run_id=uuid4(), action_id="search-1")

    result = await registry.execute(
        name="search.official",
        context=context,
        arguments={"query": "华为开发者大赛 截止", "official_domains": ["developer.huawei.com"]},
    )

    assert result.status is ToolStatus.SUCCESS
    assert result.data["provider"] == "recording"
    assert len(result.data["items"]) >= 1
    assert result.source_refs


@pytest.mark.asyncio
async def test_search_verified_deadline_policy() -> None:
    policy = ToolPolicy()
    definition = ToolDefinition(
        "state.set_deadline",
        "deadline",
        ToolRisk.SENSITIVE_WRITE,
        _unused_handler,
        replay_policy=ToolReplayPolicy.IDEMPOTENT,
    )
    evidence_url = "https://developer.huawei.com/article/1"
    state = {
        "tool_results": [
            {
                "status": "SUCCESS",
                "tool_name": "search.official",
                "data": {
                    "items": [{"url": evidence_url, "title": "t", "snippet": "s"}],
                },
            }
        ]
    }
    blocked = policy.evaluate(
        definition,
        state=state,
        arguments={
            "thing_id": str(uuid4()),
            "certainty": "CONFIRMED",
            "is_primary": True,
            "evidence_urls": [evidence_url],
        },
    )
    assert blocked.decision is PolicyDecision.ALLOW
    assert blocked.code == "SEARCH_VERIFIED_DEADLINE"

    missing = policy.evaluate(
        definition,
        state=state,
        arguments={
            "thing_id": str(uuid4()),
            "certainty": "CONFIRMED",
            "is_primary": True,
        },
    )
    assert missing.decision is PolicyDecision.REQUIRE_MORE_CONTEXT
