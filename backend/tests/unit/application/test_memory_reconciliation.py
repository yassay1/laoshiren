from uuid import uuid4

from laoshiren.application.memories.candidate import MemoryCandidate, MemoryCandidateAction
from laoshiren.application.memories.reconciliation import (
    StateFactSnapshot,
    duplicates_current_state,
    should_ignore_candidate,
)
from laoshiren.domain.memories.entities import MemoryType


def test_duplicates_current_state_matches_active_task_title() -> None:
    snapshot = StateFactSnapshot(fact_lines=("准备答辩材料",))

    assert duplicates_current_state(content="准备答辩材料", snapshot=snapshot)


def test_should_ignore_suppressed_or_state_duplicate() -> None:
    candidate = MemoryCandidate(
        memory_type=MemoryType.SEMANTIC,
        content="准备答辩材料",
        action=MemoryCandidateAction.CREATE,
    )
    snapshot = StateFactSnapshot(fact_lines=("准备答辩材料",))

    assert should_ignore_candidate(candidate, snapshot=snapshot, suppressed=True)
    assert should_ignore_candidate(candidate, snapshot=snapshot, suppressed=False)


def test_rrf_prefers_items_ranked_in_both_lists() -> None:
    from laoshiren.application.memories.retrieval import reciprocal_rank_fusion

    first = uuid4()
    second = uuid4()
    third = uuid4()

    fused = reciprocal_rank_fusion((first, second), (second, third))

    assert fused[0] is second
    assert set(fused) == {first, second, third}
