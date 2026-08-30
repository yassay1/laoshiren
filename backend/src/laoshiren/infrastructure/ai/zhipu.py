import json
from dataclasses import replace
from typing import Any

import httpx

from laoshiren.agent.contracts import ExecutiveDecision, GraphState
from laoshiren.agent.model_gateway import ModelGatewayError
from laoshiren.agent.parallel import parse_executive_decision
from laoshiren.agent.prompts import build_executive_user_payload, render_executive_system_prompt


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
        self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
    ) -> ExecutiveDecision:
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": render_executive_system_prompt(tool_manifest),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        build_executive_user_payload(state=state, available_tools=available_tools),
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
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
        except httpx.TransportError as exc:
            raise ModelGatewayError(
                "MODEL_PROVIDER_UNAVAILABLE",
                "The model provider transport failed.",
                retryable=True,
            ) from exc
        self._raise_for_error(response)
        body: Any = response.json()
        try:
            content = body["choices"][0]["message"]["content"]
            decision = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ModelGatewayError(
                "MODEL_INVALID_RESPONSE",
                "Zhipu returned an invalid decision payload.",
                retryable=True,
            ) from exc
        normalized = parse_executive_decision(decision, available_tools=available_tools)
        usage = body.get("usage", {}) if isinstance(body, dict) else {}
        return replace(
            normalized,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
        )

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
