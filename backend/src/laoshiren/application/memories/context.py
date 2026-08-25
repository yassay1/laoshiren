from dataclasses import dataclass
from difflib import SequenceMatcher
from hashlib import sha256
from uuid import UUID

from laoshiren.application.ai.ports import EmbeddingProvider, EmbeddingProviderError
from laoshiren.application.memories.dto import MemoryDTO
from laoshiren.application.memories.service import MemoryApplicationService
from laoshiren.domain.memories.entities import MemoryType


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


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    memory_type: MemoryType
    content: str
    confidence: float
    run_id: UUID
    source_message_ids: tuple[UUID, ...]
    profile_key: str | None = None


_STATE_AUTHORITY_TERMS = ("任务状态", "截止日期", "deadline", "已经完成任务", "thing 状态")


def extract_memory_candidate(
    *, text: str, run_id: UUID, source_message_id: UUID
) -> MemoryCandidate | None:
    normalized = " ".join(text.strip().split())
    if not normalized or any(term in normalized.casefold() for term in _STATE_AUTHORITY_TERMS):
        return None
    rules: tuple[tuple[str, MemoryType, float], ...] = (
        ("请记住：", MemoryType.SEMANTIC, 1.0),
        ("请记住:", MemoryType.SEMANTIC, 1.0),
        ("记住我", MemoryType.PROFILE, 0.95),
        ("我喜欢", MemoryType.PROFILE, 0.85),
        ("我偏好", MemoryType.PROFILE, 0.9),
        ("以后请", MemoryType.PROFILE, 0.9),
    )
    for prefix, memory_type, confidence in rules:
        if normalized.startswith(prefix):
            content = normalized[len(prefix) :].lstrip("：:，, ")
            if len(content) < 2:
                return None
            return MemoryCandidate(
                memory_type=memory_type,
                content=content,
                confidence=confidence,
                run_id=run_id,
                source_message_ids=(source_message_id,),
                profile_key=(
                    _profile_key(content) if memory_type is MemoryType.PROFILE else None
                ),
            )
    return None


def _profile_key(content: str) -> str:
    value = content.casefold()
    if any(word in value for word in ("回答", "回复", "简洁", "详细", "语气")):
        return "preference:response_style"
    if "提醒" in value:
        return "preference:reminder"
    if any(word in value for word in ("中文", "英文", "语言")):
        return "preference:language"
    return "preference:general"


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

    async def form_from_user_input(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        source_message_id: UUID,
        text: str,
    ) -> MemoryDTO | None:
        candidate = extract_memory_candidate(
            text=text, run_id=run_id, source_message_id=source_message_id
        )
        if candidate is None or candidate.confidence < 0.75:
            return None
        existing = await self._memories.search(
            user_id=user_id,
            query=candidate.content,
            memory_type=candidate.memory_type,
            limit=5,
        )
        canonical = " ".join(candidate.content.casefold().split())
        for memory in existing:
            existing_canonical = " ".join(memory.content.casefold().split())
            if (
                existing_canonical == canonical
                or SequenceMatcher(None, existing_canonical, canonical).ratio() >= 0.92
            ):
                return memory
        embedding = None
        if self._embedding_provider is not None:
            try:
                embedding = await self._embedding_provider.embed(candidate.content)
            except EmbeddingProviderError:
                embedding = None
        return await self._memories.create(
            user_id=user_id,
            memory_type=candidate.memory_type,
            content=candidate.content,
            summary=candidate.content[:200],
            importance=0.8 if candidate.memory_type is MemoryType.PROFILE else 0.65,
            confidence=candidate.confidence,
            idempotency_key=(
                f"agent-memory:{run_id}:"
                f"{sha256(canonical.encode()).hexdigest()[:16]}"
            ),
            embedding=embedding,
            profile_key=candidate.profile_key,
            provenance_run_id=candidate.run_id,
            source_message_ids=candidate.source_message_ids,
        )
