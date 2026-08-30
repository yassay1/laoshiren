from datetime import UTC, datetime
from uuid import uuid4

import pytest

from laoshiren.application.memories.candidate import MemoryCandidate, MemoryCandidateAction
from laoshiren.application.memories.context import MemoryContext
from laoshiren.application.memories.dto import MemoryDTO
from laoshiren.application.memories.manager import MemoryFormationContext, MemoryManager
from laoshiren.domain.memories.entities import MemoryStatus, MemoryType

pytestmark = pytest.mark.gate_b


def _memory_dto(content: str, memory_type: MemoryType) -> MemoryDTO:
    now = datetime.now(UTC)
    return MemoryDTO(
        id=uuid4(),
        user_id=uuid4(),
        memory_type=memory_type,
        content=content,
        summary=content,
        importance=0.7,
        confidence=0.9,
        thing_id=None,
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
        updated_at=now,
        last_accessed_at=None,
    )


class _StaticExtractor:
    def __init__(self, candidates: tuple[MemoryCandidate, ...]) -> None:
        self._candidates = candidates

    async def extract(self, *, context: MemoryFormationContext) -> tuple[MemoryCandidate, ...]:
        return self._candidates


class _FakeMemories:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []

    async def create_if_allowed(self, **values: object) -> MemoryDTO | None:
        self.created.append(values)
        return _memory_dto(str(values["content"]), values["memory_type"])  # type: ignore[arg-type]


def _formation_context() -> MemoryFormationContext:
    return MemoryFormationContext(
        user_id=uuid4(),
        run_id=uuid4(),
        user_text="hello",
    )


def test_memory_context_marks_non_authoritative_authority() -> None:
    memory = _memory_dto("偏好安静酒店", MemoryType.PROFILE)
    payload = MemoryContext(profile=(memory,), relevant=()).as_prompt_data()
    assert payload["authority"] == "NON-AUTHORITATIVE LONG-TERM MEMORY"


@pytest.mark.asyncio
async def test_memory_formation_rejects_state_authority_content() -> None:
    memories = _FakeMemories()
    manager = MemoryManager(
        memories,  # type: ignore[arg-type]
        _StaticExtractor(
            (
                MemoryCandidate(
                    memory_type=MemoryType.SEMANTIC,
                    content="这个任务的截止日期是周五",
                    action=MemoryCandidateAction.CREATE,
                ),
            )
        ),
    )
    formed = await manager.form(context=_formation_context())
    assert formed == ()
    assert memories.created == []
