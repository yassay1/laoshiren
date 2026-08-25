from dataclasses import dataclass, field
from difflib import SequenceMatcher
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from laoshiren.application.ai.ports import EmbeddingProvider, EmbeddingProviderError
from laoshiren.application.memories.candidate import (
    MemoryCandidate,
    MemoryCandidateAction,
    rejects_state_authority,
)
from laoshiren.application.memories.dto import MemoryDTO
from laoshiren.application.memories.service import MemoryApplicationService
from laoshiren.domain.memories.entities import MemoryType


@dataclass(frozen=True, slots=True)
class MemoryFormationContext:
    """Inputs assembled for one formation pass (数据设计 §27)."""

    user_id: UUID
    run_id: UUID
    user_text: str
    source_message_id: UUID | None = None
    recent_messages: tuple[str, ...] = field(default_factory=tuple)
    state_mutation_summaries: tuple[str, ...] = field(default_factory=tuple)
    existing_memories: tuple[MemoryDTO, ...] = field(default_factory=tuple)
    active_thing_ids: tuple[UUID, ...] = field(default_factory=tuple)


class MemoryExtractor(Protocol):
    """LLM boundary that decides what to remember (数据设计 §27 Memory Manager)."""

    async def extract(
        self, *, context: MemoryFormationContext
    ) -> tuple[MemoryCandidate, ...]: ...


def profile_key_for(content: str) -> str:
    value = content.casefold()
    if any(word in value for word in ("回答", "回复", "简洁", "详细", "语气")):
        return "preference:response_style"
    if "提醒" in value:
        return "preference:reminder"
    if any(word in value for word in ("中文", "英文", "语言")):
        return "preference:language"
    return "preference:general"


class MemoryManager:
    """Orchestrates LLM-driven formation and executes candidate actions deterministically."""

    def __init__(
        self,
        memories: MemoryApplicationService,
        extractor: MemoryExtractor,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        confidence_threshold: float = 0.7,
    ) -> None:
        if not 0 <= confidence_threshold <= 1:
            raise ValueError("Memory confidence threshold must be between 0 and 1.")
        self._memories = memories
        self._extractor = extractor
        self._embedding_provider = embedding_provider
        self._confidence_threshold = confidence_threshold

    async def form_from_event(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        source_message_id: UUID,
        user_text: str,
        recent_messages: tuple[str, ...] = (),
        state_mutation_summaries: tuple[str, ...] = (),
        active_thing_ids: tuple[UUID, ...] = (),
    ) -> tuple[MemoryDTO, ...]:
        existing = await self._memories.search(user_id=user_id, query=user_text, limit=8)
        context = MemoryFormationContext(
            user_id=user_id,
            run_id=run_id,
            source_message_id=source_message_id,
            user_text=user_text,
            recent_messages=recent_messages,
            state_mutation_summaries=state_mutation_summaries,
            existing_memories=tuple(existing),
            active_thing_ids=active_thing_ids,
        )
        return await self.form(context=context)

    async def remember(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        content: str,
        memory_type: MemoryType,
        source_message_id: UUID | None = None,
        thing_id: UUID | None = None,
    ) -> MemoryDTO:
        """Explicit-command path: the user already said what to remember (数据设计 §16)."""
        canonical = " ".join(content.casefold().split())
        existing = await self._memories.search(
            user_id=user_id, query=content, memory_type=memory_type, limit=8
        )
        for memory in existing:
            existing_canonical = " ".join(memory.content.casefold().split())
            if (
                existing_canonical == canonical
                or SequenceMatcher(None, existing_canonical, canonical).ratio() >= 0.92
            ):
                return memory
        candidate = MemoryCandidate(
            memory_type=memory_type,
            content=content,
            action=MemoryCandidateAction.CREATE,
            thing_id=thing_id,
        )
        context = MemoryFormationContext(
            user_id=user_id,
            run_id=run_id,
            source_message_id=source_message_id,
            user_text=content,
        )
        formed = await self._apply(candidate=candidate, context=context)
        assert formed is not None
        return formed

    async def forget(
        self,
        *,
        user_id: UUID,
        memory_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> MemoryDTO:
        """User data-control path: soft-delete a memory (数据设计 §9.3)."""
        return await self._memories.update(
            user_id=user_id,
            memory_id=memory_id,
            expected_version=expected_version,
            content=None,
            summary=None,
            importance=None,
            confidence=None,
            idempotency_key=idempotency_key,
            delete=True,
        )

    async def form(self, *, context: MemoryFormationContext) -> tuple[MemoryDTO, ...]:
        candidates = await self._extractor.extract(context=context)
        formed: list[MemoryDTO] = []
        for candidate in candidates:
            if candidate.action is MemoryCandidateAction.IGNORE:
                continue
            if candidate.confidence < self._confidence_threshold:
                continue
            if rejects_state_authority(candidate.content):
                continue
            memory = await self._apply(candidate=candidate, context=context)
            if memory is not None:
                formed.append(memory)
        return tuple(formed)

    async def _apply(
        self, *, candidate: MemoryCandidate, context: MemoryFormationContext
    ) -> MemoryDTO | None:
        summary = candidate.content[:200]
        idempotency_key = self._idempotency_key(context=context, candidate=candidate)
        embedding = await self._embed(candidate.content)

        if candidate.action is MemoryCandidateAction.SUPERSEDE:
            target_id = candidate.target_memory_id
            assert target_id is not None  # guaranteed by MemoryCandidate.__post_init__
            target = await self._memories.get(
                user_id=context.user_id, memory_id=target_id
            )
            await self._memories.update(
                user_id=context.user_id,
                memory_id=target.id,
                expected_version=target.version,
                content=None,
                summary=None,
                importance=None,
                confidence=None,
                idempotency_key=f"{idempotency_key}:supersede",
                supersede=True,
            )

        if candidate.action in {
            MemoryCandidateAction.UPDATE,
            MemoryCandidateAction.MERGE,
        }:
            target_id = candidate.target_memory_id
            assert target_id is not None  # guaranteed by MemoryCandidate.__post_init__
            target = await self._memories.get(
                user_id=context.user_id, memory_id=target_id
            )
            return await self._memories.update(
                user_id=context.user_id,
                memory_id=target.id,
                expected_version=target.version,
                content=candidate.content,
                summary=summary,
                importance=candidate.importance,
                confidence=candidate.confidence,
                idempotency_key=idempotency_key,
            )

        return await self._memories.create(
            user_id=context.user_id,
            memory_type=candidate.memory_type,
            content=candidate.content,
            summary=summary,
            importance=candidate.importance,
            confidence=candidate.confidence,
            idempotency_key=idempotency_key,
            thing_id=candidate.thing_id,
            source_ids=candidate.source_refs,
            embedding=embedding,
            profile_key=(
                profile_key_for(candidate.content)
                if candidate.memory_type is MemoryType.PROFILE
                else None
            ),
            provenance_run_id=context.run_id,
            source_message_ids=(
                (context.source_message_id,) if context.source_message_id is not None else ()
            ),
        )

    async def _embed(self, text: str) -> list[float] | None:
        if self._embedding_provider is None:
            return None
        try:
            return await self._embedding_provider.embed(text)
        except EmbeddingProviderError:
            return None

    @staticmethod
    def _idempotency_key(
        *, context: MemoryFormationContext, candidate: MemoryCandidate
    ) -> str:
        canonical = " ".join(candidate.content.casefold().split())
        digest = sha256(canonical.encode()).hexdigest()[:16]
        return f"agent-memory:{context.run_id}:{digest}"
