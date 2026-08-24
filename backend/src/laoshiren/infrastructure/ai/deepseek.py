import json
from typing import Any

import httpx

from laoshiren.agent.contracts import DecisionKind, ExecutiveDecision, GraphState
from laoshiren.agent.model_gateway import ModelGatewayError

_SYSTEM_PROMPT = """你是“老实人”的单一 Executive Agent。
只决定下一步，不得声称未执行的工具已经成功，不得输出私有推理过程。
请只返回 JSON 对象，格式只能是以下三种之一：
{"kind":"respond","content":"给用户的最终回复"}
{"kind":"ask_user","prompt":{"type":"input","message":"需要澄清的问题"}}
{"kind":"call_tool","tool_name":"可用工具名","tool_arguments":{}}

工具参数：state.get_thing(thing_id)；state.list_things(query?,limit?)；
state.list_tasks(thing_id)；state.get_timeline(thing_id,limit?)；
state.create_thing(name,reason?)；state.create_task(thing_id,title,reason?)；
state.complete_task(task_id,expected_version,reason?)；
state.set_deadline(thing_id,value,timezone,certainty,expected_version,
kind?,precision?,is_primary?,reason?)。
Personal State 是当前现实状态权威来源。不确定信息不得正式写入；缺少关键语义、ID、
版本或时区时先查询或 ask_user。每次只选择一个动作。
"""


class DeepSeekExecutiveModelGateway:
    """DeepSeek Chat Completions adapter using the provider's JSON mode."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "deepseek-v4-flash",
        api_base: str = "https://api.deepseek.com",
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("DeepSeek API key is required.")
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
            raise ModelGatewayError(
                "MODEL_INVALID_RESPONSE",
                "DeepSeek returned an invalid decision payload.",
                retryable=True,
            ) from exc
        return self._parse_decision(decision, available_tools=available_tools)

    @staticmethod
    def _raise_for_error(response: httpx.Response) -> None:
        if response.is_success:
            return
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
            raise ModelGatewayError(
                "MODEL_INVALID_RESPONSE", "Model decision must be an object.", retryable=True
            )
        try:
            kind = DecisionKind(str(value["kind"]))
        except (KeyError, ValueError) as exc:
            raise ModelGatewayError(
                "MODEL_INVALID_RESPONSE", "Model decision kind is invalid.", retryable=True
            ) from exc
        if kind is DecisionKind.RESPOND:
            return ExecutiveDecision(kind, content=str(value.get("content", "")).strip())
        if kind is DecisionKind.ASK_USER:
            prompt = value.get("prompt")
            if not isinstance(prompt, dict):
                raise ModelGatewayError(
                    "MODEL_INVALID_RESPONSE",
                    "Model ask-user prompt must be an object.",
                    retryable=True,
                )
            return ExecutiveDecision(kind, prompt=prompt)
        tool_name = str(value.get("tool_name", ""))
        if tool_name not in available_tools:
            raise ModelGatewayError(
                "MODEL_INVALID_RESPONSE",
                "Model selected an unavailable tool.",
                retryable=True,
            )
        arguments = value.get("tool_arguments", {})
        if not isinstance(arguments, dict):
            raise ModelGatewayError(
                "MODEL_INVALID_RESPONSE",
                "Model tool arguments must be an object.",
                retryable=True,
            )
        return ExecutiveDecision(kind, tool_name=tool_name, tool_arguments=arguments)
