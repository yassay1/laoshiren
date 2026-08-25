from typing import Any, cast
from uuid import uuid4

import pytest

from laoshiren.agent.contracts import ToolResult, ToolStatus
from laoshiren.agent.tools import (
    ToolDefinition,
    ToolExecutionContext,
    ToolRegistry,
    ToolReplayPolicy,
    ToolRisk,
    build_tool_manifest,
    register_automation_tools,
    register_memory_tools,
    register_personal_state_tools,
)
from laoshiren.application.automations.service import AutomationApplicationService
from laoshiren.application.memories.context import AgentMemoryApplicationService
from laoshiren.application.personal_state.dto import MutationResultDTO
from laoshiren.application.personal_state.service import PersonalStateApplicationService

pytestmark = pytest.mark.asyncio


class RecordingArchiveService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def archive_thing(self, **kwargs: Any) -> MutationResultDTO:
        self.calls.append(("archive_thing", kwargs))
        return MutationResultDTO(uuid4(), kwargs["thing_id"], 3)


async def test_archive_thing_tool_is_sensitive_and_injects_identity() -> None:
    service = RecordingArchiveService()
    registry = ToolRegistry()
    register_personal_state_tools(
        registry, cast(PersonalStateApplicationService, service)
    )
    context = ToolExecutionContext(user_id=uuid4(), run_id=uuid4(), action_id="arch-1")
    thing_id = uuid4()

    result = await registry.execute(
        name="state.archive_thing",
        context=context,
        arguments={"thing_id": str(thing_id), "expected_version": 2},
    )

    assert result.status is ToolStatus.SUCCESS
    assert result.mutation_refs
    assert service.calls == [
        (
            "archive_thing",
            {
                "user_id": context.user_id,
                "thing_id": thing_id,
                "expected_version": 2,
                "action_id": "arch-1",
                "idempotency_key": f"agent:{context.run_id}:arch-1",
                "reason": "Agent archived Thing",
                "run_id": context.run_id,
            },
        )
    ]
    assert registry.get("state.archive_thing").risk is ToolRisk.SENSITIVE_WRITE


async def test_memory_search_tool_is_registered_read_only() -> None:
    class RecordingMemoryService:
        async def search(self, **kwargs: Any) -> tuple[Any, ...]:
            del kwargs
            return ()

    registry = ToolRegistry()
    register_memory_tools(
        registry, cast(AgentMemoryApplicationService, RecordingMemoryService())
    )

    definition = registry.get("memory.search")
    assert definition is not None
    assert definition.risk is ToolRisk.READ
    assert definition.replay_policy is ToolReplayPolicy.READ_ONLY
    assert definition.required_arguments == ("query",)


async def test_automation_tools_are_registered_reversible_write() -> None:
    class RecordingAutomationService:
        async def create(self, **kwargs: Any) -> Any:
            del kwargs
            raise AssertionError("not called")

        async def change_status(self, **kwargs: Any) -> Any:
            del kwargs
            raise AssertionError("not called")

    registry = ToolRegistry()
    register_automation_tools(
        registry, cast(AutomationApplicationService, RecordingAutomationService())
    )

    create = registry.get("automation.create")
    change = registry.get("automation.change")
    assert create is not None and create.risk is ToolRisk.REVERSIBLE_WRITE
    assert create.replay_policy is ToolReplayPolicy.IDEMPOTENT
    assert change is not None and change.risk is ToolRisk.REVERSIBLE_WRITE


async def test_build_tool_manifest_renders_name_description_and_arguments() -> None:
    async def noop(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        del context, arguments
        return ToolResult(ToolStatus.SUCCESS, "OK", "ok")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            "state.read_thing",
            "Read a Thing.",
            ToolRisk.READ,
            noop,
            required_arguments=("thing_id",),
        )
    )

    manifest = build_tool_manifest(registry)

    assert "state.read_thing：Read a Thing.；参数：thing_id" in manifest


async def test_missing_required_argument_returns_user_input() -> None:
    service = RecordingArchiveService()
    registry = ToolRegistry()
    register_personal_state_tools(
        registry, cast(PersonalStateApplicationService, service)
    )

    result = await registry.execute(
        name="state.archive_thing",
        context=ToolExecutionContext(uuid4(), uuid4(), "arch-1"),
        arguments={},
    )

    assert result.status is ToolStatus.REQUIRES_USER_INPUT
    assert result.data == {"missing": ["thing_id", "expected_version"]}
