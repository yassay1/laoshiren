from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from laoshiren.application.memories.dto import MemoryDTO
from laoshiren.application.memories.service import MemoryApplicationService
from laoshiren.domain.memories.entities import MemoryType


class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class EmbeddingProviderError(RuntimeError):
    """Embedding infrastructure failed; callers may use lexical retrieval."""


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
    """Bounded retrieval and conservative explicit memory formation for Agent Runs."""

    def __init__(
        self,
        memories: MemoryApplicationService,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._memories = memories
        self._embedding_provider = embedding_provider

    async def load_context(
        self, *, user_id: UUID, query: str, profile_limit: int = 6, relevant_limit: int = 6
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
        combined = sorted(
            [*semantic, *episodic],
            key=lambda memory: (memory.importance, memory.confidence, memory.updated_at),
            reverse=True,
        )[:relevant_limit]
        return MemoryContext(tuple(profile), tuple(combined))

    async def form_from_user_input(
        self, *, user_id: UUID, run_id: UUID, text: str
    ) -> MemoryDTO | None:
        normalized = text.strip()
        prefixes = (("请记住：", MemoryType.SEMANTIC), ("请记住:", MemoryType.SEMANTIC))
        memory_type = None
        content = ""
        for prefix, candidate_type in prefixes:
            if normalized.startswith(prefix):
                memory_type = candidate_type
                content = normalized[len(prefix) :].strip()
                break
        if memory_type is None and normalized.startswith("记住我"):
            memory_type = MemoryType.PROFILE
            content = normalized[3:].lstrip("：:，, ")
        if memory_type is None or len(content) < 2:
            return None
        existing = await self._memories.search(
            user_id=user_id, query=content, memory_type=memory_type, limit=5
        )
        canonical = " ".join(content.casefold().split())
        for memory in existing:
            if " ".join(memory.content.casefold().split()) == canonical:
                return memory
        embedding = None
        if self._embedding_provider is not None:
            try:
                embedding = await self._embedding_provider.embed(content)
            except EmbeddingProviderError:
                embedding = None
        return await self._memories.create(
            user_id=user_id,
            memory_type=memory_type,
            content=content,
            summary=content[:200],
            importance=0.8 if memory_type is MemoryType.PROFILE else 0.65,
            confidence=1.0,
            idempotency_key=f"agent-memory:{run_id}",
            embedding=embedding,
        )
