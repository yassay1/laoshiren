"""DurableJob enqueue for background Memory formation."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.domain.runtime.entities import DurableJob, DurableJobKind


@dataclass(frozen=True, slots=True)
class MemoryFormationEvent:
    """Signal that a Run finished and memory formation is due."""

    user_id: UUID
    run_id: UUID
    thread_id: UUID
    source_message_id: UUID
    user_text: str
    tool_result_codes: tuple[str, ...] = field(default_factory=tuple)


async def enqueue_memory_formation(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    event: MemoryFormationEvent,
) -> None:
    dedupe_key = f"memory-formation:{event.run_id}"
    existing = await uow.durable_jobs.get_by_dedupe_key(user_id=user_id, dedupe_key=dedupe_key)
    if existing is not None:
        return
    await uow.durable_jobs.add(
        DurableJob(
            user_id=user_id,
            kind=DurableJobKind.MEMORY_FORMATION,
            dedupe_key=dedupe_key,
            payload={
                "run_id": str(event.run_id),
                "thread_id": str(event.thread_id),
                "source_message_id": str(event.source_message_id),
                "user_text": event.user_text,
                "tool_result_codes": list(event.tool_result_codes),
            },
            available_at=datetime.now(UTC),
        )
    )


def event_from_job_payload(*, user_id: UUID, payload: dict[str, object]) -> MemoryFormationEvent:
    tool_codes_raw = payload.get("tool_result_codes", [])
    tool_result_codes = (
        tuple(str(code) for code in tool_codes_raw)
        if isinstance(tool_codes_raw, list)
        else ()
    )
    return MemoryFormationEvent(
        user_id=user_id,
        run_id=UUID(str(payload["run_id"])),
        thread_id=UUID(str(payload["thread_id"])),
        source_message_id=UUID(str(payload["source_message_id"])),
        user_text=str(payload["user_text"]),
        tool_result_codes=tool_result_codes,
    )
