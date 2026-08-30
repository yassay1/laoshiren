import json
from typing import Any
from uuid import UUID

import httpx

from laoshiren.application.memories.candidate import MemoryCandidate, MemoryCandidateAction
from laoshiren.application.memories.manager import MemoryFormationContext
from laoshiren.domain.memories.entities import MemoryType


class MemoryExtractorError(RuntimeError):
    """The model provider could not produce a valid memory candidate list."""


_MEMORY_MANAGER_PROMPT = """你是“老实人”的记忆管理器（Memory Manager）。
你的唯一任务是：从对话中抽取真正值得长期记住的信息，输出结构化记忆操作。

三类长期记忆：
- PROFILE：稳定的用户偏好或长期特征（如“喜欢简洁提醒”）。
- SEMANTIC：跨对话仍有长期价值的事实、决策、关系（如“客户端决定用 ArkTS”）。
- EPISODIC：过去的重要经历，要包含“发生了什么 + 结果如何 + 未来类似场景的参考价值”
  （如“上次正式汇报先重新搭故事线，比直接拼旧材料效果更好”）。

规则：
1. 当前任务状态（截止日期、任务完成情况、当前进度）属于 Personal State，绝不写成 Memory。
2. 没有值得长期记住的内容时，返回空数组 []。
3. 对每条候选给出 action：
   - CREATE：新建一条记忆。
   - UPDATE：更新已有记忆（提供 target_memory_id）。
   - SUPERSEDE：新记忆取代旧记忆（提供 target_memory_id，旧记忆会被标记失效）。
   - IGNORE：本次不记（等同省略）。
4. importance 与 confidence 取值 0~1。

只返回 JSON 数组，不要输出任何解释文字：
[
  {"memory_type": "PROFILE", "content": "用户偏好简洁提醒", "action": "CREATE",
   "reason": "用户明确表达偏好", "importance": 0.9, "confidence": 0.9,
   "thing_id": null, "target_memory_id": null}
]"""


def _render_context(context: MemoryFormationContext) -> str:
    existing = [
        {"id": str(memory.id), "type": memory.memory_type.value, "content": memory.content}
        for memory in context.existing_memories
    ]
    return json.dumps(
        {
            "用户这条消息": context.user_text,
            "最近对话": list(context.recent_messages),
            "最近的个人状态变更": list(context.state_mutation_summaries),
            "已存在的相关记忆": existing,
        },
        ensure_ascii=False,
    )


class OpenAIMemoryExtractor:
    """LLM-driven memory extractor for OpenAI-compatible chat completions."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        api_base: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Memory extractor API key is required.")
        self._api_key = api_key
        self._model = model
        self._url = f"{api_base.rstrip('/')}/chat/completions"
        self._timeout = timeout_seconds

    async def extract(self, *, context: MemoryFormationContext) -> tuple[MemoryCandidate, ...]:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _MEMORY_MANAGER_PROMPT},
                {"role": "user", "content": _render_context(context)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 2048,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                self._url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
        if not response.is_success:
            raise MemoryExtractorError(
                f"Memory extractor request failed with status {response.status_code}."
            )
        body: Any = response.json()
        try:
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise MemoryExtractorError("Memory extractor returned an invalid payload.") from exc
        return self._parse_candidates(parsed)

    @staticmethod
    def _parse_candidates(parsed: Any) -> tuple[MemoryCandidate, ...]:
        if not isinstance(parsed, list):
            # Some providers wrap a list under {"memories": [...]} in JSON mode.
            if isinstance(parsed, dict):
                nested = parsed.get("memories")
                if isinstance(nested, list):
                    parsed = nested
                else:
                    raise MemoryExtractorError("Memory extractor payload must be a list.")
            else:
                raise MemoryExtractorError("Memory extractor payload must be a list.")
        candidates: list[MemoryCandidate] = []
        for item in parsed:
            candidate = OpenAIMemoryExtractor._parse_candidate(item)
            if candidate is not None:
                candidates.append(candidate)
        return tuple(candidates)

    @staticmethod
    def _parse_candidate(item: Any) -> MemoryCandidate | None:
        if not isinstance(item, dict):
            return None
        try:
            memory_type = MemoryType(str(item["memory_type"]))
            action = MemoryCandidateAction(str(item["action"]))
            content = str(item["content"]).strip()
            reason = str(item.get("reason", ""))
            importance = float(item.get("importance", 0.6))
            confidence = float(item.get("confidence", 0.7))
        except (KeyError, ValueError, TypeError):
            return None
        if not content or not 0 <= importance <= 1 or not 0 <= confidence <= 1:
            return None
        thing_id_value = item.get("thing_id")
        target_value = item.get("target_memory_id")
        try:
            thing_id = UUID(str(thing_id_value)) if thing_id_value else None
            target_id = UUID(str(target_value)) if target_value else None
            return MemoryCandidate(
                memory_type=memory_type,
                content=content,
                action=action,
                reason=reason,
                importance=importance,
                confidence=confidence,
                thing_id=thing_id,
                target_memory_id=target_id,
            )
        except (ValueError, TypeError):
            return None
