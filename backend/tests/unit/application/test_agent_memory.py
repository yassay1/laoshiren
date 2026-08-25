from datetime import UTC, datetime
from uuid import uuid4

import pytest

from laoshiren.application.ai.ports import EmbeddingProviderError
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


class FakeMemories:
    def __init__(self) -> None:
        self.profile = [memory_dto("用户喜欢简洁回答", MemoryType.PROFILE, 0.9)]
        self.semantic = [memory_dto("项目使用 PostgreSQL", MemoryType.SEMANTIC, 0.8)]
        self.episodic = [memory_dto("上次修复了恢复问题", MemoryType.EPISODIC, 0.5)]

    async def search(self, **values: object) -> list[MemoryDTO]:
        memory_type = values.get("memory_type")
        if memory_type is None:
            return [*self.profile, *self.semantic, *self.episodic]
        return {
            MemoryType.PROFILE: self.profile,
            MemoryType.SEMANTIC: self.semantic,
            MemoryType.EPISODIC: self.episodic,
        }.get(memory_type, [])


class FailingEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        raise EmbeddingProviderError("provider unavailable")

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingProviderError("provider unavailable")


async def test_context_is_bounded_and_separates_profile_from_relevant() -> None:
    memories = FakeMemories()
    service = AgentMemoryApplicationService(memories)  # type: ignore[arg-type]

    context = await service.load_context(user_id=uuid4(), query="PostgreSQL", relevant_limit=1)

    assert [item.content for item in context.profile] == ["用户喜欢简洁回答"]
    assert [item.content for item in context.relevant] == ["项目使用 PostgreSQL"]


async def test_embedding_failure_falls_back_to_lexical_retrieval() -> None:
    memories = FakeMemories()
    service = AgentMemoryApplicationService(
        memories,  # type: ignore[arg-type]
        embedding_provider=FailingEmbeddingProvider(),
    )

    context = await service.load_context(user_id=uuid4(), query="PostgreSQL")
    results = await service.search(user_id=uuid4(), query="PostgreSQL")

    assert context.relevant
    assert results


async def test_search_returns_memories_across_types() -> None:
    memories = FakeMemories()
    service = AgentMemoryApplicationService(memories)  # type: ignore[arg-type]

    results = await service.search(user_id=uuid4(), query="项目")

    assert any(item.memory_type is MemoryType.SEMANTIC for item in results)
