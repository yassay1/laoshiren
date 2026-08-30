"""Commit-time reconciliation between Memory candidates and Personal State."""

from dataclasses import dataclass
from uuid import UUID

from laoshiren.application.memories.candidate import MemoryCandidate, rejects_state_authority
from laoshiren.application.memories.fingerprint import canonicalize_memory_content
from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.domain.personal_state.value_objects import TaskStatus, ThingStatus


@dataclass(frozen=True, slots=True)
class StateFactSnapshot:
    """Compact current-reality lines used to reject stale Memory candidates."""

    fact_lines: tuple[str, ...]


async def load_state_fact_snapshot(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    thing_limit: int = 20,
) -> StateFactSnapshot:
    lines: list[str] = []
    things = await uow.things.list_active(user_id=user_id, limit=thing_limit)
    for thing in things:
        if thing.status is not ThingStatus.ACTIVE:
            continue
        lines.append(canonicalize_memory_content(thing.name))
        if thing.current_stage:
            lines.append(
                canonicalize_memory_content(f"{thing.name} {thing.current_stage}")
            )
        if thing.deadline_at is not None:
            lines.append(
                canonicalize_memory_content(
                    f"{thing.name} deadline {thing.deadline_at.date().isoformat()}"
                )
            )
        tasks = await uow.tasks.list_for_thing(user_id=user_id, thing_id=thing.id)
        for task in tasks:
            if task.status in {TaskStatus.DONE, TaskStatus.CANCELLED}:
                continue
            lines.append(canonicalize_memory_content(task.title))
            lines.append(
                canonicalize_memory_content(f"{thing.name} {task.title} {task.status.value}")
            )
    standalone = await uow.tasks.list_standalone(user_id=user_id)
    for task in standalone:
        if task.status in {TaskStatus.DONE, TaskStatus.CANCELLED}:
            continue
        lines.append(canonicalize_memory_content(task.title))
    return StateFactSnapshot(fact_lines=tuple(dict.fromkeys(line for line in lines if line)))


def duplicates_current_state(*, content: str, snapshot: StateFactSnapshot) -> bool:
    normalized = canonicalize_memory_content(content)
    if not normalized:
        return True
    for fact in snapshot.fact_lines:
        if len(fact) < 4:
            continue
        if fact == normalized or fact in normalized or normalized in fact:
            return True
    return False


def should_ignore_candidate(
    candidate: MemoryCandidate,
    *,
    snapshot: StateFactSnapshot,
    suppressed: bool,
) -> bool:
    if suppressed:
        return True
    if rejects_state_authority(candidate.content):
        return True
    return duplicates_current_state(content=candidate.content, snapshot=snapshot)
