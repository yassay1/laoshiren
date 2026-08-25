from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from laoshiren.application.memories.context import rank_memories
from laoshiren.application.memories.dto import MemoryDTO
from laoshiren.domain.memories.entities import MemoryStatus, MemoryType


def memory_dto(
    content: str,
    memory_type: MemoryType,
    importance: float,
    *,
    thing_id: UUID | None = None,
    updated_at: datetime | None = None,
) -> MemoryDTO:
    now = datetime.now(UTC)
    return MemoryDTO(
        id=uuid4(),
        user_id=uuid4(),
        memory_type=memory_type,
        content=content,
        summary=content,
        importance=importance,
        confidence=1.0,
        thing_id=thing_id,
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
        updated_at=updated_at or now,
        last_accessed_at=None,
    )


def test_thing_match_boosts_relevant_memory() -> None:
    active = uuid4()
    on_thing = memory_dto("on", MemoryType.SEMANTIC, 0.3, thing_id=active)
    off_thing = memory_dto("off", MemoryType.SEMANTIC, 0.5)

    ranked = rank_memories([off_thing, on_thing], active_thing_ids=(active,))

    assert ranked[0].content == "on"


def test_importance_dominates_without_thing_match() -> None:
    low = memory_dto("low", MemoryType.SEMANTIC, 0.3)
    high = memory_dto("high", MemoryType.SEMANTIC, 0.9)

    ranked = rank_memories([low, high])

    assert ranked[0].content == "high"


def test_episodic_gets_lower_type_weight() -> None:
    semantic = memory_dto("semantic", MemoryType.SEMANTIC, 0.5)
    episodic = memory_dto("episodic", MemoryType.EPISODIC, 0.6)

    ranked = rank_memories([episodic, semantic])

    # 0.5 * 1.0 = 0.5  vs  0.6 * 0.8 = 0.48  → semantic wins despite lower raw importance
    assert ranked[0].content == "semantic"


def test_recency_breaks_ties() -> None:
    older = memory_dto(
        "older",
        MemoryType.SEMANTIC,
        0.5,
        updated_at=datetime.now(UTC) - timedelta(days=2),
    )
    newer = memory_dto("newer", MemoryType.SEMANTIC, 0.5, updated_at=datetime.now(UTC))

    ranked = rank_memories([older, newer])

    assert ranked[0].content == "newer"
