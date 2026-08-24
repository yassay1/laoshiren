from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from laoshiren.application.ai.ports import EmbeddingProviderError
from laoshiren.application.memories.context import (
    AgentMemoryApplicationService,
    extract_memory_candidate,
)
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


async def test_only_explicit_memory_request_is_formed_and_is_idempotent_per_run() -> None:
    memories = FakeMemories()
    service = AgentMemoryApplicationService(memories)  # type: ignore[arg-type]
    user_id = UUID("00000000-0000-0000-0000-000000000001")
    run_id = uuid4()
    message_id = uuid4()

    assert await service.form_from_user_input(
        user_id=user_id, run_id=run_id, source_message_id=message_id, text="今天天气怎么样"
    ) is None
    formed = await service.form_from_user_input(
        user_id=user_id,
        run_id=run_id,
        source_message_id=message_id,
        text="请记住：新的长期事实",
    )

    assert formed is not None
    assert formed.content == "新的长期事实"
    assert str(memories.created[0]["idempotency_key"]).startswith(
        f"agent-memory:{run_id}:"
    )
    assert memories.created[0]["source_message_ids"] == (message_id,)


async def test_embedding_failure_falls_back_without_failing_agent_memory() -> None:
    memories = FakeMemories()
    service = AgentMemoryApplicationService(
        memories,  # type: ignore[arg-type]
        embedding_provider=FailingEmbeddingProvider(),
    )

    context = await service.load_context(user_id=uuid4(), query="PostgreSQL")
    formed = await service.form_from_user_input(
        user_id=uuid4(),
        run_id=uuid4(),
        source_message_id=uuid4(),
        text="请记住：新的长期事实",
    )

    assert context.relevant
    assert formed is not None
    assert memories.created[-1]["embedding"] is None


async def test_candidate_extraction_rejects_personal_state_and_keys_profile() -> None:
    run_id = uuid4()
    message_id = uuid4()

    profile = extract_memory_candidate(
        text="以后请用简洁的中文回答",
        run_id=run_id,
        source_message_id=message_id,
    )
    state_fact = extract_memory_candidate(
        text="请记住：任务状态已经完成",
        run_id=run_id,
        source_message_id=message_id,
    )

    assert profile is not None
    assert profile.memory_type is MemoryType.PROFILE
    assert profile.profile_key == "preference:response_style"
    assert profile.source_message_ids == (message_id,)
    assert state_fact is None


async def test_near_duplicate_candidate_reuses_existing_memory() -> None:
    memories = FakeMemories()
    existing = memory_dto("项目长期使用 PostgreSQL 数据库", MemoryType.SEMANTIC, 0.8)
    memories.semantic = [existing]
    service = AgentMemoryApplicationService(memories)  # type: ignore[arg-type]

    formed = await service.form_from_user_input(
        user_id=uuid4(),
        run_id=uuid4(),
        source_message_id=uuid4(),
        text="请记住：项目长期使用 PostgreSQL 数据库。",
    )

    assert formed is existing
    assert memories.created == []
