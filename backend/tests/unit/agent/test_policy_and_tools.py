from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest

from laoshiren.agent.contracts import ToolStatus
from laoshiren.agent.policy import PolicyDecision, ToolPolicy
from laoshiren.agent.tools import (
    ToolDefinition,
    ToolExecutionContext,
    ToolRegistry,
    ToolRisk,
    register_personal_state_tools,
)
from laoshiren.application.personal_state.dto import MutationResultDTO, ThingDTO
from laoshiren.application.personal_state.service import PersonalStateApplicationService
from laoshiren.domain.personal_state.value_objects import ThingStatus

pytestmark = pytest.mark.asyncio


async def _unused_handler(
    context: ToolExecutionContext, arguments: dict[str, Any]
) -> Any:
    raise AssertionError((context, arguments))


async def test_policy_matrix_is_deterministic() -> None:
    policy = ToolPolicy()
    read = ToolDefinition("read", "read", ToolRisk.READ, _unused_handler)
    write = ToolDefinition("write", "write", ToolRisk.REVERSIBLE_WRITE, _unused_handler)
    sensitive = ToolDefinition("sensitive", "sensitive", ToolRisk.SENSITIVE_WRITE, _unused_handler)
    irreversible = ToolDefinition("delete", "delete", ToolRisk.IRREVERSIBLE, _unused_handler)
    disabled = ToolDefinition("off", "off", ToolRisk.READ, _unused_handler, enabled=False)

    assert policy.evaluate(read).decision is PolicyDecision.ALLOW
    assert policy.evaluate(write).decision is PolicyDecision.ALLOW
    assert policy.evaluate(sensitive).decision is PolicyDecision.REQUIRE_CONFIRMATION
    assert policy.evaluate(irreversible).decision is PolicyDecision.REQUIRE_CONFIRMATION
    assert policy.evaluate(disabled).decision is PolicyDecision.DENY


class RecordingPersonalStateService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get_thing(self, **kwargs: Any) -> ThingDTO:
        self.calls.append(("get_thing", kwargs))
        now = datetime.now(UTC)
        return ThingDTO(
            id=kwargs["thing_id"],
            user_id=kwargs["user_id"],
            name="测试事务",
            status=ThingStatus.ACTIVE,
            current_stage=None,
            deadline_at=None,
            version=2,
            created_at=now,
            updated_at=now,
        )

    async def complete_task(self, **kwargs: Any) -> MutationResultDTO:
        self.calls.append(("complete_task", kwargs))
        return MutationResultDTO(uuid4(), kwargs["task_id"], 4)


async def test_tool_adapter_injects_runtime_identity_and_idempotency() -> None:
    service = RecordingPersonalStateService()
    registry = ToolRegistry()
    register_personal_state_tools(
        registry, cast(PersonalStateApplicationService, service)
    )
    context = ToolExecutionContext(user_id=uuid4(), run_id=uuid4(), action_id="action-1")
    task_id = uuid4()

    result = await registry.execute(
        name="state.complete_task",
        context=context,
        arguments={"task_id": str(task_id), "expected_version": 3},
    )

    assert result.status is ToolStatus.SUCCESS
    assert service.calls == [
        (
            "complete_task",
            {
                "user_id": context.user_id,
                "task_id": task_id,
                "expected_version": 3,
                "action_id": "action-1",
                "idempotency_key": f"agent:{context.run_id}:action-1",
                "reason": "Agent completed Task",
                "run_id": context.run_id,
            },
        )
    ]
    assert registry.get("state.set_deadline").risk is ToolRisk.SENSITIVE_WRITE


async def test_tool_adapter_normalizes_invalid_arguments() -> None:
    registry = ToolRegistry()
    register_personal_state_tools(
        registry,
        cast(PersonalStateApplicationService, RecordingPersonalStateService()),
    )
    result = await registry.execute(
        name="state.get_thing",
        context=ToolExecutionContext(uuid4(), uuid4(), "bad"),
        arguments={"thing_id": "not-a-uuid"},
    )
    assert result.status is ToolStatus.FAILED
    assert result.code == "INVALID_ARGUMENT"

    missing = await registry.execute(
        name="state.complete_task",
        context=ToolExecutionContext(uuid4(), uuid4(), "missing"),
        arguments={},
    )
    assert missing.status is ToolStatus.REQUIRES_USER_INPUT
    assert missing.data == {"missing": ["task_id", "expected_version"]}
