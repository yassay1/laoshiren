from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest

from laoshiren.agent.contracts import ToolStatus
from laoshiren.agent.policy import PolicyDecision, ToolPolicy
from laoshiren.agent.tools import (
    ToolDefinition,
    ToolExecutionContext,
    ToolRegistry,
    ToolReplayPolicy,
    ToolRisk,
    register_personal_state_tools,
)
from laoshiren.application.personal_state.dto import MutationResultDTO, ThingDTO
from laoshiren.application.personal_state.service import PersonalStateApplicationService
from laoshiren.domain.personal_state.value_objects import TaskStatus, ThingStatus

pytestmark = pytest.mark.asyncio


async def _unused_handler(context: ToolExecutionContext, arguments: dict[str, object]) -> object:
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


async def test_set_deadline_confirmed_without_source_requires_more_context() -> None:
    policy = ToolPolicy()
    definition = ToolDefinition(
        "thing_date_set",
        "deadline",
        ToolRisk.SENSITIVE_WRITE,
        _unused_handler,
        replay_policy=ToolReplayPolicy.IDEMPOTENT,
    )
    result = policy.evaluate(
        definition,
        arguments={
            "thing_id": "00000000-0000-0000-0000-000000000001",
            "certainty": "CONFIRMED",
            "is_primary": True,
        },
    )
    assert result.decision is PolicyDecision.REQUIRE_MORE_CONTEXT
    assert result.code == "DEADLINE_NEEDS_VERIFICATION"


async def test_set_deadline_with_source_allows_first_confirmed_write() -> None:
    policy = ToolPolicy()
    definition = ToolDefinition(
        "thing_date_set",
        "deadline",
        ToolRisk.SENSITIVE_WRITE,
        _unused_handler,
        replay_policy=ToolReplayPolicy.IDEMPOTENT,
    )
    result = policy.evaluate(
        definition,
        arguments={
            "thing_id": "00000000-0000-0000-0000-000000000001",
            "certainty": "CONFIRMED",
            "is_primary": True,
            "source_id": "00000000-0000-0000-0000-000000000002",
        },
    )
    assert result.decision is PolicyDecision.ALLOW
    assert result.code == "SOURCE_VERIFIED_DEADLINE"


async def test_write_tool_requires_replay_contract_and_context_key_is_stable() -> None:
    registry = ToolRegistry()
    with pytest.raises(ValueError, match="explicit replay policy"):
        registry.register(
            ToolDefinition("unsafe.write", "write", ToolRisk.REVERSIBLE_WRITE, _unused_handler)
        )
    registry.register(
        ToolDefinition(
            "safe.write",
            "write",
            ToolRisk.REVERSIBLE_WRITE,
            _unused_handler,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
        )
    )
    context = ToolExecutionContext(uuid4(), uuid4(), "stable-action")

    assert context.idempotency_key == f"agent:{context.run_id}:stable-action"


class RecordingPersonalStateService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def get_thing(self, **kwargs: object) -> ThingDTO:
        self.calls.append(("get_thing", kwargs))
        now = datetime.now(UTC)
        return ThingDTO(
            id=kwargs["thing_id"],  # type: ignore[index]
            user_id=kwargs["user_id"],  # type: ignore[index]
            name="测试事务",
            status=ThingStatus.ACTIVE,
            current_stage=None,
            deadline_at=None,
            merged_into_thing_id=None,
            deleted_at=None,
            version=2,
            created_at=now,
            updated_at=now,
        )

    async def transition_task(self, **kwargs: object) -> MutationResultDTO:
        self.calls.append(("transition_task", kwargs))
        return MutationResultDTO(uuid4(), kwargs["task_id"], 4)  # type: ignore[index]


async def test_tool_adapter_injects_runtime_identity_and_idempotency() -> None:
    service = RecordingPersonalStateService()
    registry = ToolRegistry()
    register_personal_state_tools(registry, cast(PersonalStateApplicationService, service))
    context = ToolExecutionContext(user_id=uuid4(), run_id=uuid4(), action_id="action-1")
    task_id = uuid4()

    result = await registry.execute(
        name="task_change_status",
        context=context,
        arguments={"task_id": str(task_id), "expected_version": 3, "target_status": "DONE"},
    )

    assert result.status is ToolStatus.SUCCESS
    assert service.calls == [
        (
            "transition_task",
            {
                "user_id": context.user_id,
                "task_id": task_id,
                "target_status": TaskStatus.DONE,
                "expected_version": 3,
                "action_id": "action-1",
                "idempotency_key": f"agent:{context.run_id}:action-1",
                "reason": "Agent changed Task status",
            },
        )
    ]
    assert registry.get("thing_date_set").risk is ToolRisk.SENSITIVE_WRITE


async def test_tool_adapter_normalizes_invalid_arguments() -> None:
    registry = ToolRegistry()
    register_personal_state_tools(
        registry,
        cast(PersonalStateApplicationService, RecordingPersonalStateService()),
    )
    result = await registry.execute(
        name="state_get_thing_context",
        context=ToolExecutionContext(uuid4(), uuid4(), "bad"),
        arguments={"thing_id": "not-a-uuid"},
    )
    assert result.status is ToolStatus.FAILED
    assert result.code == "INVALID_ARGUMENT"

    missing = await registry.execute(
        name="task_change_status",
        context=ToolExecutionContext(uuid4(), uuid4(), "missing"),
        arguments={},
    )
    assert missing.status is ToolStatus.REQUIRES_USER_INPUT
    assert missing.data == {"missing": ["task_id", "target_status", "expected_version"]}
