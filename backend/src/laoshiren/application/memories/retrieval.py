"""Lexical + vector hybrid retrieval with Reciprocal Rank Fusion."""

from uuid import UUID

from laoshiren.application.memories.ports import MemoryUnitOfWork
from laoshiren.domain.memories.entities import Memory, MemoryStatus, MemoryType

DEFAULT_RRF_K = 60
DEFAULT_CANDIDATE_MULTIPLIER = 3


def reciprocal_rank_fusion(
    *ranked_ids: tuple[UUID, ...],
    k: int = DEFAULT_RRF_K,
) -> list[UUID]:
    scores: dict[UUID, float] = {}
    for ranked in ranked_ids:
        for rank, item_id in enumerate(ranked, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + (1.0 / (k + rank))
    return sorted(scores, key=lambda item_id: (-scores[item_id], str(item_id)))


async def hybrid_search_memories(
    uow: MemoryUnitOfWork,
    *,
    user_id: UUID,
    query: str | None,
    memory_type: MemoryType | None,
    thing_id: UUID | None,
    query_embedding: list[float] | None,
    limit: int,
    candidate_multiplier: int = DEFAULT_CANDIDATE_MULTIPLIER,
) -> list[Memory]:
    candidate_limit = max(limit, limit * candidate_multiplier)
    lexical: list[Memory] = []
    if query and query.strip():
        lexical = await uow.memories.search(
            user_id=user_id,
            query=query.strip(),
            memory_type=memory_type,
            status=MemoryStatus.ACTIVE,
            thing_id=thing_id,
            query_embedding=None,
            limit=candidate_limit,
        )
    vector: list[Memory] = []
    if query_embedding is not None:
        vector = await uow.memories.search(
            user_id=user_id,
            query=None,
            memory_type=memory_type,
            status=MemoryStatus.ACTIVE,
            thing_id=thing_id,
            query_embedding=query_embedding,
            limit=candidate_limit,
        )
    if lexical and vector:
        by_id = {memory.id: memory for memory in [*lexical, *vector]}
        fused_ids = reciprocal_rank_fusion(
            tuple(memory.id for memory in lexical),
            tuple(memory.id for memory in vector),
        )
        return [by_id[item_id] for item_id in fused_ids[:limit] if item_id in by_id]
    if vector:
        return vector[:limit]
    if lexical:
        return lexical[:limit]
    return await uow.memories.search(
        user_id=user_id,
        query=query,
        memory_type=memory_type,
        status=MemoryStatus.ACTIVE,
        thing_id=thing_id,
        query_embedding=None,
        limit=limit,
    )
