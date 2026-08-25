import json
from dataclasses import dataclass
from typing import Any

from laoshiren.application.personal_state.dto import StateOverviewDTO
from laoshiren.application.runtime.dto import MessageDTO


@dataclass(frozen=True, slots=True)
class AgentContext:
    messages: list[dict[str, Any]]
    prefetched_state: dict[str, Any]


class AgentContextBuilder:
    """Build bounded transient model context without deleting durable messages."""

    def __init__(
        self,
        *,
        total_characters: int = 24_000,
        recent_message_characters: int = 8_000,
        summary_characters: int = 3_000,
        memory_characters: int = 5_000,
        source_characters: int = 8_000,
        state_overview_characters: int = 3_000,
        recent_message_count: int = 20,
    ) -> None:
        limits = (
            total_characters,
            recent_message_characters,
            summary_characters,
            memory_characters,
            source_characters,
            state_overview_characters,
            recent_message_count,
        )
        if any(value <= 0 for value in limits):
            raise ValueError("Context budgets must be positive.")
        self._total = total_characters
        self._recent_characters = recent_message_characters
        self._summary_characters = summary_characters
        self._memory_characters = memory_characters
        self._source_characters = source_characters
        self._overview_characters = state_overview_characters
        self._recent_count = recent_message_count

    def build(
        self,
        *,
        messages: list[MessageDTO],
        memory_context: dict[str, Any] | None = None,
        source_context: list[dict[str, str]] | None = None,
        state_overview: StateOverviewDTO | None = None,
    ) -> AgentContext:
        recent = self._recent_messages(messages)
        recent_ids = {str(message["id"]) for message in recent}
        omitted = [message for message in messages if str(message.id) not in recent_ids]
        summary = self._summarize(omitted)

        used = sum(len(str(item["content"])) for item in recent) + len(summary)
        remaining = max(0, self._total - used)
        memory_budget = min(self._memory_characters, remaining)
        bounded_memory = self._trim_memory(memory_context or {}, memory_budget)
        remaining -= self._measure_memory(bounded_memory)
        bounded_sources = self._trim_sources(
            source_context or [], min(self._source_characters, max(0, remaining))
        )
        bounded_overview = (
            self._trim_overview(
                overview_to_prompt_data(state_overview), self._overview_characters
            )
            if state_overview is not None
            else {}
        )
        prefetched: dict[str, Any] = {
            "memory_context": bounded_memory,
            "source_context": bounded_sources,
            "context_stats": {
                "durable_message_count_loaded": len(messages),
                "recent_message_count": len(recent),
                "summarized_message_count": len(omitted),
                "character_budget": self._total,
            },
        }
        if bounded_overview:
            prefetched["state_overview"] = bounded_overview
        if summary:
            prefetched["thread_summary"] = summary
        return AgentContext(messages=recent, prefetched_state=prefetched)

    def _recent_messages(self, messages: list[MessageDTO]) -> list[dict[str, Any]]:
        selected: list[MessageDTO] = []
        used = 0
        for message in reversed(messages):
            content_length = len(message.content)
            if selected and (
                len(selected) >= self._recent_count
                or used + content_length > self._recent_characters
            ):
                break
            selected.append(message)
            used += content_length
        selected.reverse()
        return [
            {
                "id": str(message.id),
                "role": message.role.value,
                "content": message.content,
                "run_id": str(message.run_id) if message.run_id is not None else None,
            }
            for message in selected
        ]

    def _summarize(self, messages: list[MessageDTO]) -> str:
        if not messages:
            return ""
        lines: list[str] = []
        per_message = max(1, self._summary_characters // len(messages))
        used = 0
        for message in messages:
            normalized = " ".join(message.content.split())
            prefix = f"{message.role.value}: "
            excerpt = normalized[: max(1, min(240, per_message - len(prefix) - 1))]
            line = f"{message.role.value}: {excerpt}"
            if used + len(line) > self._summary_characters:
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines)

    @staticmethod
    def _trim_memory(value: dict[str, Any], budget: int) -> dict[str, Any]:
        result: dict[str, Any] = {"profile": [], "relevant": []}
        remaining = budget
        for group in ("profile", "relevant"):
            items = value.get(group, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                cost = len(str(item.get("content", ""))) + len(
                    str(item.get("summary", ""))
                )
                if cost > remaining:
                    break
                result[group].append(item)
                remaining -= cost
        return result

    @staticmethod
    def _measure_memory(value: dict[str, Any]) -> int:
        return sum(
            len(str(item.get("content", ""))) + len(str(item.get("summary", "")))
            for group in ("profile", "relevant")
            for item in value.get(group, [])
            if isinstance(item, dict)
        )

    @staticmethod
    def _trim_sources(
        values: list[dict[str, str]], budget: int
    ) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        remaining = budget
        for value in values:
            content = value.get("content", "")
            if remaining <= 0:
                break
            trimmed = content[:remaining]
            if trimmed:
                result.append({**value, "content": trimmed})
                remaining -= len(trimmed)
        return result

    @staticmethod
    def _trim_overview(data: dict[str, Any], budget: int) -> dict[str, Any]:
        if not data:
            return {}
        if len(json.dumps(data, ensure_ascii=False, default=str)) <= budget:
            return data
        result: dict[str, Any] = {}
        for section, items in data.items():
            result[section] = []
            for item in items:
                result[section].append(item)
                if len(json.dumps(result, ensure_ascii=False, default=str)) > budget:
                    result[section].pop()
                    return result
        return result


def overview_to_prompt_data(overview: StateOverviewDTO) -> dict[str, Any]:
    return {
        "upcoming": [
            {
                "name": item.name,
                "deadline": item.deadline_at.isoformat(),
                "open_tasks": item.open_task_count,
            }
            for item in overview.upcoming
        ],
        "blocked": [
            {
                "thing": item.thing_name,
                "description": item.description,
                "severity": item.severity.value,
            }
            for item in overview.blocked
        ],
        "active": [
            {
                "name": item.name,
                "stage": item.current_stage,
                "open_tasks": item.open_task_count,
            }
            for item in overview.active
        ],
        "recent": [
            {
                "name": item.name,
                "status": item.status.value,
                "updated_at": item.updated_at.isoformat(),
            }
            for item in overview.recent
        ],
    }
