from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from laoshiren.domain.memories.entities import MemoryType


class MemoryCandidateAction(StrEnum):
    """What the Memory Manager decided to do with a candidate (数据设计 §28)."""

    CREATE = "CREATE"
    UPDATE = "UPDATE"
    MERGE = "MERGE"
    SUPERSEDE = "SUPERSEDE"
    IGNORE = "IGNORE"


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    """A structured memory operation proposed by the LLM Memory Manager."""

    memory_type: MemoryType
    content: str
    action: MemoryCandidateAction
    reason: str = ""
    importance: float = 0.6
    confidence: float = 0.7
    thing_id: UUID | None = None
    source_refs: tuple[UUID, ...] = field(default_factory=tuple)
    target_memory_id: UUID | None = None

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("Memory candidate content must not be empty.")
        if not 0 <= self.importance <= 1 or not 0 <= self.confidence <= 1:
            raise ValueError("Memory importance and confidence must be between 0 and 1.")
        if (
            self.action
            in {
                MemoryCandidateAction.UPDATE,
                MemoryCandidateAction.MERGE,
                MemoryCandidateAction.SUPERSEDE,
            }
            and self.target_memory_id is None
        ):
            raise ValueError(f"Memory action {self.action.value} requires a target memory id.")


def profile_key_for(content: str) -> str:
    value = content.casefold()
    if any(word in value for word in ("回答", "回复", "简洁", "详细", "语气")):
        return "preference:response_style"
    if "提醒" in value:
        return "preference:reminder"
    if any(word in value for word in ("中文", "英文", "语言")):
        return "preference:language"
    return "preference:general"


_STATE_AUTHORITY_TERMS = ("截止日期", "deadline", "任务状态", "thing 状态")


def rejects_state_authority(text: str) -> bool:
    """Deterministic safety gate: current reality belongs to Personal State, not Memory.

    This is the one rule the LLM may not override (数据设计 §19 优先级铁律).
    """
    normalized = " ".join(text.strip().split())
    if not normalized:
        return True
    return any(term in normalized.casefold() for term in _STATE_AUTHORITY_TERMS)


_EXPLICIT_MEMORY_TERMS = ("请记住", "记住这个", "记下来", "别忘了", "记住我")


def is_explicit_memory_command(text: str) -> bool:
    """Whether the user explicitly asked to remember something (数据设计 §16 立即触发)."""
    normalized = " ".join(text.strip().split())
    return any(term in normalized for term in _EXPLICIT_MEMORY_TERMS)
