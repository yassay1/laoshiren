import re
from typing import Any

from laoshiren.application.personal_state.dto import (
    BlockerDTO,
    TaskDTO,
    ThingDateDTO,
    ThingDTO,
)
from laoshiren.domain.personal_state.value_objects import TaskStatus


def thing_search_query_from_input(text: str) -> str:
    """Extract a compact Thing lookup token from natural-language input."""
    normalized = text.strip()
    if not normalized:
        return ""
    latin_tokens = re.findall(r"[A-Za-z]{2,}", normalized)
    if latin_tokens:
        return str(latin_tokens[0])
    return normalized


def thing_prefetch_payload(
    *,
    thing: ThingDTO,
    tasks: list[TaskDTO],
    blockers: list[BlockerDTO],
    dates: list[ThingDateDTO],
    match_reason: str,
) -> dict[str, Any]:
    open_tasks = [
        task for task in tasks if task.status not in {TaskStatus.DONE, TaskStatus.CANCELLED}
    ]
    primary_dates = [item for item in dates if item.is_primary][:3]
    return {
        "match_status": "resolved",
        "match_reason": match_reason,
        "thing": {
            "id": str(thing.id),
            "name": thing.name,
            "status": thing.status.value,
            "current_stage": thing.current_stage,
            "deadline_at": thing.deadline_at.isoformat() if thing.deadline_at else None,
            "version": thing.version,
        },
        "open_tasks": [
            {
                "id": str(task.id),
                "title": task.title,
                "status": task.status.value,
                "version": task.version,
            }
            for task in open_tasks[:12]
        ],
        "blockers": [
            {
                "id": str(blocker.id),
                "description": blocker.description,
                "severity": blocker.severity.value,
                "version": blocker.version,
            }
            for blocker in blockers[:6]
        ],
        "primary_dates": [
            {
                "id": str(item.id),
                "kind": item.kind,
                "value": item.value.isoformat(),
                "certainty": item.certainty.value,
                "version": item.version,
            }
            for item in primary_dates
        ],
    }


def ambiguous_thing_candidates(things: list[ThingDTO]) -> dict[str, Any]:
    return {
        "match_status": "ambiguous",
        "candidates": [
            {
                "id": str(thing.id),
                "name": thing.name,
                "status": thing.status.value,
                "version": thing.version,
            }
            for thing in things
        ],
    }
