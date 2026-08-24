import json
from typing import Any

import httpx

from laoshiren.agent.contracts import DecisionKind, ExecutiveDecision, GraphState
from laoshiren.agent.model_gateway import ModelGatewayError

_SYSTEM_PROMPT = """你是“老实人”的单一 Executive Agent。
你只负责决定下一步，不得声称未执行的工具已经成功，也不得输出私有推理过程。
必须返回一个 JSON 对象，且只能是以下三种之一：
1. {"kind":"respond","content":"给用户的最终回复"}
2. {"kind":"ask_user","prompt":{"type":"input","message":"需要澄清的问题"}}
3. {"kind":"call_tool","tool_name":"可用工具名","tool_arguments":{...}}

核心工具参数：
- state.get_thing: thing_id
- state.list_things: query(可选), limit(可选)
- state.list_tasks: thing_id
- state.get_timeline: thing_id, limit(可选)
- state.create_thing: name, reason(可选)
- state.create_task: thing_id, title, reason(可选)
- state.complete_task: task_id, expected_version, reason(可选)
- state.set_deadline: thing_id, value(含时区ISO8601), timezone, certainty,
  expected_version, kind/precision/is_primary/reason(可选)

Personal State 是当前现实状态权威来源；不确定信息不得写成正式状态。缺少 ID、版本、
时区或关键语义时先查询或 ask_user。每次只选择一个动作。
"""


class ZhipuExecutiveModelGateway:
    """智谱 HTTP adapter; no provider SDK types cross this boundary."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "glm-5.2",
        api_base: str = "https://open.bigmodel.cn/api/paas/v4",
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Zhipu API key is required.")
        self._api_key = api_key
        self._model = model
        self._url = f"{api_base.rstrip('/')}/chat/completions"
        self._timeout = timeout_seconds

    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...]
    ) -> ExecutiveDecision:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "current_input": state.get("current_input", ""),
                            "conversation": state.get("messages", [])[-20:],
                            "tool_results": state.get("tool_results", [])[-10:],
                            "memory_context": state.get("prefetched_state", {}).get(
                                "memory_context", {}
                            ),
                            "source_context": state.get("prefetched_state", {}).get(
                                "source_context", []
                            ),
                            "available_tools": list(available_tools),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
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
        self._raise_for_error(response)
        body: Any = response.json()
        try:
            content = body["choices"][0]["message"]["content"]
            decision = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Zhipu returned an invalid decision payload.") from exc
        return self._parse_decision(decision, available_tools=available_tools)

    @staticmethod
    def _raise_for_error(response: httpx.Response) -> None:
        if response.is_success:
            return
        provider_code = ""
        try:
            error = response.json().get("error", {})
            provider_code = str(error.get("code", ""))
        except (TypeError, ValueError):
            pass
        if response.status_code == 429 and provider_code == "1113":
            raise ModelGatewayError(
                "MODEL_QUOTA_EXHAUSTED",
                "The configured model account has no available quota.",
                retryable=False,
            )
        if response.status_code in {401, 403}:
            raise ModelGatewayError(
                "MODEL_AUTH_FAILED",
                "The model provider rejected the configured credentials.",
                retryable=False,
            )
        retryable = response.status_code == 429 or response.status_code >= 500
        raise ModelGatewayError(
            "MODEL_PROVIDER_UNAVAILABLE" if retryable else "MODEL_REQUEST_REJECTED",
            "The model provider could not complete the request.",
            retryable=retryable,
        )

    @staticmethod
    def _parse_decision(
        value: Any, *, available_tools: tuple[str, ...]
    ) -> ExecutiveDecision:
        if not isinstance(value, dict):
            raise RuntimeError("Model decision must be an object.")
        try:
            kind = DecisionKind(str(value["kind"]))
        except (KeyError, ValueError) as exc:
            raise RuntimeError("Model decision kind is invalid.") from exc
        if kind is DecisionKind.RESPOND:
            return ExecutiveDecision(kind, content=str(value.get("content", "")).strip())
        if kind is DecisionKind.ASK_USER:
            prompt = value.get("prompt")
            if not isinstance(prompt, dict):
                raise RuntimeError("Model ask-user prompt must be an object.")
            return ExecutiveDecision(kind, prompt=prompt)
        tool_name = str(value.get("tool_name", ""))
        if tool_name not in available_tools:
            raise RuntimeError("Model selected an unavailable tool.")
        arguments = value.get("tool_arguments", {})
        if not isinstance(arguments, dict):
            raise RuntimeError("Model tool arguments must be an object.")
        return ExecutiveDecision(kind, tool_name=tool_name, tool_arguments=arguments)
