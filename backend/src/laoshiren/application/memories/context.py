from dataclasses import dataclass
from uuid import UUID

from laoshiren.application.ai.ports import EmbeddingProvider, EmbeddingProviderError
from laoshiren.application.memories.dto import MemoryDTO
from laoshiren.application.memories.service import MemoryApplicationService
from laoshiren.domain.memories.entities import MemoryType

_MEMORY_TYPE_WEIGHTS = {
    MemoryType.PROFILE: 1.0,
    MemoryType.SEMANTIC: 1.0,
    MemoryType.EPISODIC: 0.8,
}


def rank_memories(
    memories: list[MemoryDTO],
    *,
    active_thing_ids: tuple[UUID, ...] = (),
) -> list[MemoryDTO]:
    """Rank by importance × type-weight + thing-match bonus (数据设计 §32)."""
    active = set(active_thing_ids)

    def score(memory: MemoryDTO) -> tuple[float, object]:
        thing_bonus = (
            1.0 if memory.thing_id is not None and memory.thing_id in active else 0.0
        )
        weight = _MEMORY_TYPE_WEIGHTS.get(memory.memory_type, 1.0)
        return (memory.importance * weight + thing_bonus, memory.updated_at)

    return sorted(memories, key=score, reverse=True)


@dataclass(frozen=True, slots=True)
class MemoryContext:
    profile: tuple[MemoryDTO, ...]
    relevant: tuple[MemoryDTO, ...]

    def as_prompt_data(self) -> dict[str, object]:
        def item(memory: MemoryDTO) -> dict[str, object]:
            return {
                "id": str(memory.id),
                "type": memory.memory_type.value,
                "summary": memory.summary,
                "content": memory.content,
                "confidence": memory.confidence,
            }

        return {
            "profile": [item(memory) for memory in self.profile],
            "relevant": [item(memory) for memory in self.relevant],
        }


class AgentMemoryApplicationService:
    """Bounded retrieval for Agent Runs; formation is handled by MemoryManager."""

    def __init__(
        self,
        memories: MemoryApplicationService,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._memories = memories
        self._embedding_provider = embedding_provider

    async def load_context(
        self,
        *,
        user_id: UUID,
        query: str,
        profile_limit: int = 6,
        relevant_limit: int = 6,
        active_thing_ids: tuple[UUID, ...] = (),
    ) -> MemoryContext:
        profile = await self._memories.search(
            user_id=user_id, memory_type=MemoryType.PROFILE, limit=profile_limit
        )
        embedding = None
        if self._embedding_provider is not None and query.strip():
            try:
                embedding = await self._embedding_provider.embed(query.strip())
            except EmbeddingProviderError:
                embedding = None
        semantic = await self._memories.search(
            user_id=user_id,
            query=None if embedding is not None else query,
            memory_type=MemoryType.SEMANTIC,
            query_embedding=embedding,
            limit=relevant_limit,
        )
        episodic = await self._memories.search(
            user_id=user_id,
            query=None if embedding is not None else query,
            memory_type=MemoryType.EPISODIC,
            query_embedding=embedding,
            limit=max(1, relevant_limit // 2),
        )
        combined = rank_memories(
            [*semantic, *episodic], active_thing_ids=active_thing_ids
        )[:relevant_limit]
        return MemoryContext(tuple(profile), tuple(combined))

    async def search(
        self, *, user_id: UUID, query: str, limit: int = 8
    ) -> tuple[MemoryDTO, ...]:
        embedding = None
        if self._embedding_provider is not None and query.strip():
            try:
                embedding = await self._embedding_provider.embed(query.strip())
            except EmbeddingProviderError:
                embedding = None
        results = await self._memories.search(
            user_id=user_id,
            query=None if embedding is not None else query,
            query_embedding=embedding,
            limit=limit,
        )
        return tuple(results)
