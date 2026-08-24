from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from laoshiren.application.memories.context import AgentMemoryApplicationService
from laoshiren.application.memories.dto import MemoryDTO
from laoshiren.domain.memories.entities import MemoryStatus, MemoryType

pytestmark = pytest.mark.asyncio


def memory_dto(content: str, memory_type: MemoryType, importance: float) -> MemoryDTO:
    now = datetime.now(UTC)
    return MemoryDTO(
        id=uuid4(),
        user_id=uuid4(),
        memory_type=memory_type,
        content=content,
        summary=content,
        importance=importance,
        confidence=1.0,
        thing_id=None,
        source_ids=(),
        valid_from=None,
        valid_until=None,
        status=MemoryStatus.ACTIVE,
        version=1,
        created_at=now,
        updated_at=now,
        last_accessed_at=None,
    )


class FakeMemories:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.profile = [memory_dto("用户喜欢简洁回答", MemoryType.PROFILE, 0.9)]
        self.semantic = [memory_dto("项目使用 PostgreSQL", MemoryType.SEMANTIC, 0.8)]
        self.episodic = [memory_dto("上次修复了恢复问题", MemoryType.EPISODIC, 0.5)]

    async def search(self, **values: object) -> list[MemoryDTO]:
        memory_type = values.get("memory_type")
        if values.get("query") == "新的长期事实":
            return []
        return {
            MemoryType.PROFILE: self.profile,
            MemoryType.SEMANTIC: self.semantic,
            MemoryType.EPISODIC: self.episodic,
        }.get(memory_type, [])

    async def create(self, **values: object) -> MemoryDTO:
        self.created.append(values)
        return memory_dto(str(values["content"]), values["memory_type"], 0.65)  # type: ignore[arg-type]


async def test_context_is_bounded_and_separates_profile_from_relevant() -> None:
    memories = FakeMemories()
    service = AgentMemoryApplicationService(memories)  # type: ignore[arg-type]

    context = await service.load_context(user_id=uuid4(), query="PostgreSQL", relevant_limit=1)

    assert [item.content for item in context.profile] == ["用户喜欢简洁回答"]
    assert [item.content for item in context.relevant] == ["项目使用 PostgreSQL"]


async def test_only_explicit_memory_request_is_formed_and_is_idempotent_per_run() -> None:
    memories = FakeMemories()
    service = AgentMemoryApplicationService(memories)  # type: ignore[arg-type]
    user_id = UUID("00000000-0000-0000-0000-000000000001")
    run_id = uuid4()

    assert await service.form_from_user_input(
        user_id=user_id, run_id=run_id, text="今天天气怎么样"
    ) is None
    formed = await service.form_from_user_input(
        user_id=user_id, run_id=run_id, text="请记住：新的长期事实"
    )

    assert formed is not None
    assert formed.content == "新的长期事实"
    assert memories.created[0]["idempotency_key"] == f"agent-memory:{run_id}"
