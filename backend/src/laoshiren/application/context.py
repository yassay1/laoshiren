import json
from dataclasses import dataclass
from typing import Any

from laoshiren.application.automations.dto import AttentionCandidateDTO
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
        attachment_characters: int = 4_000,
        state_overview_characters: int = 3_000,
        active_thing_characters: int = 4_000,
        attention_characters: int = 2_000,
        recent_message_count: int = 20,
    ) -> None:
        limits = (
            total_characters,
            recent_message_characters,
            summary_characters,
            memory_characters,
            source_characters,
            attachment_characters,
            state_overview_characters,
            active_thing_characters,
            attention_characters,
            recent_message_count,
        )
        if any(value <= 0 for value in limits):
            raise ValueError("Context budgets must be positive.")
        self._total = total_characters
        self._recent_characters = recent_message_characters
        self._summary_characters = summary_characters
        self._memory_characters = memory_characters
        self._source_characters = source_characters
        self._attachment_characters = attachment_characters
        self._overview_characters = state_overview_characters
        self._active_thing_characters = active_thing_characters
        self._attention_characters = attention_characters
        self._recent_count = recent_message_count

    def build(
        self,
        *,
        messages: list[MessageDTO],
        memory_context: dict[str, Any] | None = None,
        source_context: list[dict[str, str]] | None = None,
        attachment_context: list[dict[str, str]] | None = None,
        state_overview: StateOverviewDTO | None = None,
        active_thing_context: dict[str, Any] | None = None,
        attention: tuple[AttentionCandidateDTO, ...] | None = None,
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
        remaining -= sum(len(str(item.get("content", ""))) for item in bounded_sources)
        bounded_attachments = self._trim_sources(
            attachment_context or [],
            min(self._attachment_characters, max(0, remaining)),
        )
        bounded_overview = (
            self._trim_overview(overview_to_prompt_data(state_overview), self._overview_characters)
            if state_overview is not None
            else {}
        )
        prefetched: dict[str, Any] = {
            "memory_context": bounded_memory,
            "source_context": bounded_sources,
            "attachment_context": bounded_attachments,
            "context_stats": {
                "durable_message_count_loaded": len(messages),
                "recent_message_count": len(recent),
                "summarized_message_count": len(omitted),
                "character_budget": self._total,
            },
        }
        if bounded_overview:
            prefetched["state_overview"] = bounded_overview
        bounded_active = self._trim_json_dict(
            active_thing_context or {}, self._active_thing_characters
        )
        if bounded_active:
            prefetched["active_thing_context"] = bounded_active
        bounded_attention = self._trim_attention(attention or (), self._attention_characters)
        if bounded_attention:
            prefetched["attention_candidates"] = bounded_attention
        if summary:
            prefetched["thread_summary"] = summary
        # This is deliberately appended after Memory/Source context.  Model
        # consumers must treat it as the current-reality authority whenever a
        # remembered assertion conflicts with durable Personal State.
        prefetched["current_reality"] = {
            "state_overview": bounded_overview,
            "active_thing_context": bounded_active,
            "attention_candidates": bounded_attention,
            "attachment_context": bounded_attachments,
        }
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
                cost = len(str(item.get("content", ""))) + len(str(item.get("summary", "")))
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
    def _trim_sources(values: list[dict[str, str]], budget: int) -> list[dict[str, str]]:
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
    def _trim_json_dict(data: dict[str, Any], budget: int) -> dict[str, Any]:
        if not data:
            return {}
        if len(json.dumps(data, ensure_ascii=False, default=str)) <= budget:
            return data
        reduced: dict[str, Any] = dict(data)
        for key in ("blockers", "primary_dates", "open_tasks", "candidates"):
            items = reduced.get(key)
            if isinstance(items, list) and items:
                reduced[key] = items[: max(1, len(items) // 2)]
                if len(json.dumps(reduced, ensure_ascii=False, default=str)) <= budget:
                    return reduced
        for key in ("blockers", "primary_dates"):
            reduced.pop(key, None)
        return reduced

    @staticmethod
    def _trim_attention(
        values: tuple[AttentionCandidateDTO, ...], budget: int
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        used = 0
        for item in values:
            payload = attention_to_prompt_data(item)
            cost = len(json.dumps(payload, ensure_ascii=False, default=str))
            if used + cost > budget:
                break
            result.append(payload)
            used += cost
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


def attention_to_prompt_data(candidate: AttentionCandidateDTO) -> dict[str, Any]:
    return {
        "subject_type": candidate.subject_type.value,
        "subject_id": str(candidate.subject_id),
        "thing_id": str(candidate.thing_id),
        "candidate_type": candidate.candidate_type,
        "severity": candidate.severity,
        "summary": candidate.summary,
        "due_at": candidate.due_at.isoformat() if candidate.due_at is not None else None,
        "next_eligible_at": (
            candidate.next_eligible_at.isoformat()
            if candidate.next_eligible_at is not None
            else None
        ),
        "acknowledged": candidate.acknowledged,
    }


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
