from typing import cast
from uuid import uuid4

import pytest

from laoshiren.agent.tools import (
    ToolExecutionContext,
    ToolRegistry,
    ToolRisk,
    register_memory_tools,
)
from laoshiren.application.memories.context import AgentMemoryApplicationService
from laoshiren.application.memories.dto import MemoryDTO
from laoshiren.application.memories.manager import MemoryManager
from laoshiren.domain.memories.entities import MemoryStatus, MemoryType

pytestmark = pytest.mark.asyncio


def memory_dto() -> MemoryDTO:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return MemoryDTO(
        id=uuid4(),
        user_id=uuid4(),
        memory_type=MemoryType.SEMANTIC,
        content="内容",
        summary="内容",
        importance=0.7,
        confidence=0.9,
        thing_id=None,
        source_ids=(),
        valid_from=None,
        valid_until=None,
        profile_key=None,
        supersedes_id=None,
        provenance_run_id=None,
        source_message_ids=(),
        status=MemoryStatus.ACTIVE,
        version=1,
        created_at=now,
        updated_at=now,
        last_accessed_at=None,
    )


class FakeMemory:
    async def search(self, **values: object) -> list[MemoryDTO]:
        del values
        return []


class RecordingManager:
    def __init__(self) -> None:
        self.remember_calls: list[dict[str, object]] = []
        self.forget_calls: list[dict[str, object]] = []

    async def remember(self, **values: object) -> MemoryDTO:
        self.remember_calls.append(values)
        return memory_dto()

    async def forget(self, **values: object) -> MemoryDTO:
        self.forget_calls.append(values)
        return memory_dto()


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_memory_tools(
        registry,
        cast(AgentMemoryApplicationService, FakeMemory()),
        cast(MemoryManager, RecordingManager()),
    )
    return registry


async def test_memory_forget_is_sensitive_and_remember_is_reversible() -> None:
    registry = build_registry()

    assert registry.get("memory_forget").risk is ToolRisk.SENSITIVE_WRITE
    assert registry.get("memory_remember").risk is ToolRisk.REVERSIBLE_WRITE
    assert registry.get("memory_search").risk is ToolRisk.READ


async def test_memory_remember_tool_delegates_to_manager() -> None:
    manager = RecordingManager()
    registry = ToolRegistry()
    register_memory_tools(
        registry,
        cast(AgentMemoryApplicationService, FakeMemory()),
        cast(MemoryManager, manager),
    )
    context = ToolExecutionContext(user_id=uuid4(), run_id=uuid4(), action_id="remember-1")

    result = await registry.execute(
        name="memory_remember",
        context=context,
        arguments={"content": "预算定为 5000", "memory_type": "SEMANTIC"},
    )

    assert result.status.value == "SUCCESS"
    assert manager.remember_calls[0]["content"] == "预算定为 5000"
    assert manager.remember_calls[0]["memory_type"] is MemoryType.SEMANTIC
    assert manager.remember_calls[0]["run_id"] == context.run_id


async def test_memory_forget_tool_delegates_to_manager() -> None:
    manager = RecordingManager()
    registry = ToolRegistry()
    register_memory_tools(
        registry,
        cast(AgentMemoryApplicationService, FakeMemory()),
        cast(MemoryManager, manager),
    )
    context = ToolExecutionContext(user_id=uuid4(), run_id=uuid4(), action_id="forget-1")
    memory_id = uuid4()

    result = await registry.execute(
        name="memory_forget",
        context=context,
        arguments={"memory_id": str(memory_id), "expected_version": 2},
    )

    assert result.status.value == "SUCCESS"
    assert manager.forget_calls[0]["memory_id"] == memory_id
    assert manager.forget_calls[0]["expected_version"] == 2
    assert manager.forget_calls[0]["idempotency_key"] == context.idempotency_key


async def test_memory_remember_without_manager_reports_unavailable() -> None:
    registry = ToolRegistry()
    register_memory_tools(
        registry,
        cast(AgentMemoryApplicationService, FakeMemory()),
        None,
    )

    result = await registry.execute(
        name="memory_remember",
        context=ToolExecutionContext(uuid4(), uuid4(), "remember-1"),
        arguments={"content": "预算 5000", "memory_type": "SEMANTIC"},
    )

    assert result.status.value == "NOT_FOUND"
    assert result.code == "MEMORY_MANAGER_UNAVAILABLE"
