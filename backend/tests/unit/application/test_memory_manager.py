from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from laoshiren.application.memories.candidate import MemoryCandidate, MemoryCandidateAction
from laoshiren.application.memories.dto import MemoryDTO
from laoshiren.application.memories.manager import (
    MemoryFormationContext,
    MemoryManager,
)
from laoshiren.domain.memories.entities import MemoryStatus, MemoryType

pytestmark = pytest.mark.asyncio


def memory_dto(
    content: str,
    memory_type: MemoryType,
    *,
    importance: float = 0.7,
    confidence: float = 0.9,
) -> MemoryDTO:
    now = datetime.now(UTC)
    return MemoryDTO(
        id=uuid4(),
        user_id=uuid4(),
        memory_type=memory_type,
        content=content,
        summary=content,
        importance=importance,
        confidence=confidence,
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


class StaticExtractor:
    def __init__(self, candidates: tuple[MemoryCandidate, ...]) -> None:
        self._candidates = candidates

    async def extract(self, *, context: MemoryFormationContext) -> tuple[MemoryCandidate, ...]:
        return self._candidates


class FakeMemories:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.updated: list[tuple[UUID, bool, str | None]] = []
        self.stored: dict[UUID, MemoryDTO] = {}

    def seed(self, memory: MemoryDTO) -> None:
        self.stored[memory.id] = memory

    async def get(self, *, user_id: UUID, memory_id: UUID) -> MemoryDTO:
        return self.stored[memory_id]

    async def create(self, **values: object) -> MemoryDTO:
        memory = memory_dto(
            str(values["content"]),
            values["memory_type"],  # type: ignore[arg-type]
            importance=float(values["importance"]),  # type: ignore[arg-type]
            confidence=float(values["confidence"]),  # type: ignore[arg-type]
        )
        self.created.append(values)
        self.stored[memory.id] = memory
        return memory

    async def create_if_allowed(self, **values: object) -> MemoryDTO | None:
        return await self.create(**values)

    async def update(
        self,
        *,
        user_id: UUID,
        memory_id: UUID,
        expected_version: int,
        content: str | None,
        summary: str | None,
        importance: float | None,
        confidence: float | None,
        idempotency_key: str,
        supersede: bool = False,
        delete: bool = False,
    ) -> MemoryDTO:
        del user_id, expected_version, summary, importance, confidence, idempotency_key, delete
        self.updated.append((memory_id, supersede, content))
        existing = self.stored[memory_id]
        updated = replace(
            existing,
            status=MemoryStatus.SUPERSEDED if supersede else existing.status,
            content=content if content is not None else existing.content,
        )
        self.stored[memory_id] = updated
        return updated


def make_context(
    user_id: UUID, run_id: UUID, message_id: UUID, text: str
) -> MemoryFormationContext:
    return MemoryFormationContext(
        user_id=user_id, run_id=run_id, source_message_id=message_id, user_text=text
    )


async def test_create_action_forms_memory_with_provenance() -> None:
    memories = FakeMemories()
    run_id = uuid4()
    message_id = uuid4()
    manager = MemoryManager(
        memories,  # type: ignore[arg-type]
        StaticExtractor(
            (
                MemoryCandidate(
                    memory_type=MemoryType.SEMANTIC,
                    content="预算定为 5000",
                    action=MemoryCandidateAction.CREATE,
                ),
            )
        ),
    )

    formed = await manager.form(context=make_context(uuid4(), run_id, message_id, "预算定为 5000"))

    assert len(formed) == 1
    assert memories.created[0]["provenance_run_id"] == run_id
    assert memories.created[0]["source_message_ids"] == (message_id,)
    assert memories.created[0]["idempotency_key"].startswith(f"agent-memory:{run_id}:")  # type: ignore[union-attr]


async def test_ignore_and_low_confidence_are_skipped() -> None:
    memories = FakeMemories()
    manager = MemoryManager(
        memories,  # type: ignore[arg-type]
        StaticExtractor(
            (
                MemoryCandidate(
                    memory_type=MemoryType.SEMANTIC,
                    content="Demo 做完了",
                    action=MemoryCandidateAction.IGNORE,
                ),
                MemoryCandidate(
                    memory_type=MemoryType.SEMANTIC,
                    content="不确定的事实",
                    action=MemoryCandidateAction.CREATE,
                    confidence=0.4,
                ),
            )
        ),
    )

    formed = await manager.form(context=make_context(uuid4(), uuid4(), uuid4(), "x"))

    assert formed == ()
    assert memories.created == []


async def test_safety_gate_rejects_state_content_before_write() -> None:
    memories = FakeMemories()
    manager = MemoryManager(
        memories,  # type: ignore[arg-type]
        StaticExtractor(
            (
                MemoryCandidate(
                    memory_type=MemoryType.SEMANTIC,
                    content="这个任务的截止日期是周五",
                    action=MemoryCandidateAction.CREATE,
                ),
            )
        ),
    )

    formed = await manager.form(context=make_context(uuid4(), uuid4(), uuid4(), "x"))

    assert formed == ()
    assert memories.created == []


async def test_supersede_marks_old_and_creates_new() -> None:
    memories = FakeMemories()
    old = memory_dto("客户端用原生开发", MemoryType.SEMANTIC)
    memories.seed(old)
    manager = MemoryManager(
        memories,  # type: ignore[arg-type]
        StaticExtractor(
            (
                MemoryCandidate(
                    memory_type=MemoryType.SEMANTIC,
                    content="客户端决定采用 ArkTS",
                    action=MemoryCandidateAction.SUPERSEDE,
                    target_memory_id=old.id,
                ),
            )
        ),
    )

    formed = await manager.form(context=make_context(uuid4(), uuid4(), uuid4(), "x"))

    assert len(formed) == 1
    assert formed[0].content == "客户端决定采用 ArkTS"
    assert memories.updated == [(old.id, True, None)]
    assert memories.stored[old.id].status is MemoryStatus.SUPERSEDED


async def test_update_action_updates_target() -> None:
    memories = FakeMemories()
    target = memory_dto("用户喜欢截止前一天提醒", MemoryType.PROFILE)
    memories.seed(target)
    manager = MemoryManager(
        memories,  # type: ignore[arg-type]
        StaticExtractor(
            (
                MemoryCandidate(
                    memory_type=MemoryType.PROFILE,
                    content="重要事情提前三天提醒",
                    action=MemoryCandidateAction.UPDATE,
                    target_memory_id=target.id,
                ),
            )
        ),
    )

    formed = await manager.form(context=make_context(uuid4(), uuid4(), uuid4(), "x"))

    assert len(formed) == 1
    assert memories.updated == [(target.id, False, "重要事情提前三天提醒")]
