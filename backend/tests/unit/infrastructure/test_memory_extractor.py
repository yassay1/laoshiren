from uuid import uuid4

import pytest

from laoshiren.application.memories.candidate import MemoryCandidateAction
from laoshiren.domain.memories.entities import MemoryType
from laoshiren.infrastructure.ai.memory_extractor import (
    MemoryExtractorError,
    OpenAIMemoryExtractor,
)


def test_parse_candidates_extracts_all_types_including_episodic() -> None:
    payload = [
        {
            "memory_type": "PROFILE",
            "content": "用户偏好简洁提醒",
            "action": "CREATE",
            "importance": 0.9,
            "confidence": 0.9,
        },
        {
            "memory_type": "EPISODIC",
            "content": "上次汇报先搭故事线效果更好",
            "action": "CREATE",
            "reason": "历史经验",
            "importance": 0.7,
            "confidence": 0.8,
        },
    ]

    candidates = OpenAIMemoryExtractor._parse_candidates(payload)

    assert len(candidates) == 2
    assert candidates[0].memory_type is MemoryType.PROFILE
    assert candidates[1].memory_type is MemoryType.EPISODIC
    assert candidates[1].content == "上次汇报先搭故事线效果更好"


def test_parse_candidates_accepts_memories_wrapper() -> None:
    wrapped = {
        "memories": [{"memory_type": "SEMANTIC", "content": "预算 5000", "action": "CREATE"}]
    }

    candidates = OpenAIMemoryExtractor._parse_candidates(wrapped)

    assert len(candidates) == 1
    assert candidates[0].memory_type is MemoryType.SEMANTIC


def test_parse_candidates_skips_invalid_items() -> None:
    payload = [
        {"memory_type": "SEMANTIC", "content": "有效", "action": "CREATE"},
        {"memory_type": "SEMANTIC", "content": "", "action": "CREATE"},
        {"memory_type": "BOGUS", "content": "无效类型", "action": "CREATE"},
        "not-a-dict",
        {"memory_type": "SEMANTIC", "content": "缺 action"},
    ]

    candidates = OpenAIMemoryExtractor._parse_candidates(payload)

    assert [c.content for c in candidates] == ["有效"]


def test_parse_candidates_rejects_non_list() -> None:
    with pytest.raises(MemoryExtractorError):
        OpenAIMemoryExtractor._parse_candidates("not a list")
    with pytest.raises(MemoryExtractorError):
        OpenAIMemoryExtractor._parse_candidates({"unexpected": "shape"})


def test_parse_candidate_preserves_target_memory_id() -> None:
    target = uuid4()
    parsed = OpenAIMemoryExtractor._parse_candidate(
        {
            "memory_type": "SEMANTIC",
            "content": "改用 ArkTS",
            "action": "SUPERSEDE",
            "target_memory_id": str(target),
        }
    )

    assert parsed is not None
    assert parsed.action is MemoryCandidateAction.SUPERSEDE
    assert parsed.target_memory_id == target
