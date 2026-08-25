from uuid import uuid4

import pytest

from laoshiren.application.memories.candidate import (
    MemoryCandidate,
    MemoryCandidateAction,
    rejects_state_authority,
)
from laoshiren.domain.memories.entities import MemoryType


def test_candidate_action_requires_target_for_mutation_actions() -> None:
    for action in (
        MemoryCandidateAction.UPDATE,
        MemoryCandidateAction.MERGE,
        MemoryCandidateAction.SUPERSEDE,
    ):
        with pytest.raises(ValueError, match="requires a target memory id"):
            MemoryCandidate(
                memory_type=MemoryType.PROFILE,
                content="用简短中文回答",
                action=action,
            )


def test_candidate_create_and_ignore_need_no_target() -> None:
    create = MemoryCandidate(
        memory_type=MemoryType.SEMANTIC, content="预算 5000", action=MemoryCandidateAction.CREATE
    )
    ignore = MemoryCandidate(
        memory_type=MemoryType.SEMANTIC, content="Demo 做完了", action=MemoryCandidateAction.IGNORE
    )
    assert create.target_memory_id is None
    assert ignore.action is MemoryCandidateAction.IGNORE


def test_candidate_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        MemoryCandidate(
            memory_type=MemoryType.SEMANTIC,
            content="x",
            action=MemoryCandidateAction.CREATE,
            importance=1.5,
        )
    with pytest.raises(ValueError, match="must not be empty"):
        MemoryCandidate(
            memory_type=MemoryType.SEMANTIC,
            content="   ",
            action=MemoryCandidateAction.CREATE,
        )


def test_safety_gate_rejects_state_authority_terms() -> None:
    assert rejects_state_authority("这个任务的截止日期是 9 月 30 日")
    assert rejects_state_authority("deadline 改到周五了")
    assert rejects_state_authority("")


def test_safety_gate_allows_long_term_facts_and_preferences() -> None:
    assert not rejects_state_authority("我喜欢安静酒店")
    assert not rejects_state_authority("预算定为 5000")
    assert not rejects_state_authority("客户端决定采用 ArkTS")
    assert not rejects_state_authority("上次汇报因为拼旧材料结构很乱")


def test_safety_gate_is_used_for_candidate_provenance() -> None:
    candidate = MemoryCandidate(
        memory_type=MemoryType.SEMANTIC,
        content="客户端采用 ArkTS",
        action=MemoryCandidateAction.CREATE,
        source_refs=(uuid4(),),
    )
    assert not rejects_state_authority(candidate.content)
