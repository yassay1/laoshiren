from uuid import uuid4

import httpx
import pytest

from laoshiren.agent.contracts import DecisionKind
from laoshiren.agent.model_gateway import ModelGatewayError
from laoshiren.agent.parallel import parse_executive_decision
from laoshiren.infrastructure.ai.zhipu import ZhipuExecutiveModelGateway


def test_zhipu_gateway_parses_supported_decisions() -> None:
    tools = ("state.get_thing",)
    response = parse_executive_decision(
        {"kind": "respond", "content": " 已收到 "}, available_tools=tools
    )
    ask = parse_executive_decision(
        {"kind": "ask_user", "prompt": {"type": "input", "message": "哪件事？"}},
        available_tools=tools,
    )
    call = parse_executive_decision(
        {
            "kind": "call_tool",
            "tool_name": "state.get_thing",
            "tool_arguments": {"thing_id": str(uuid4())},
        },
        available_tools=tools,
    )

    assert response.kind is DecisionKind.RESPOND
    assert response.content == "已收到"
    assert ask.kind is DecisionKind.ASK_USER
    assert call.tool_name == "state.get_thing"


def test_zhipu_gateway_rejects_unavailable_tool() -> None:
    with pytest.raises(ModelGatewayError, match="unavailable tool"):
        parse_executive_decision(
            {"kind": "call_tool", "tool_name": "system.shell", "tool_arguments": {}},
            available_tools=("state.get_thing",),
        )


def test_zhipu_gateway_normalizes_exhausted_quota() -> None:
    response = httpx.Response(
        429,
        request=httpx.Request("POST", "https://example.test/chat/completions"),
        json={"error": {"code": "1113", "message": "provider detail"}},
    )

    with pytest.raises(ModelGatewayError) as captured:
        ZhipuExecutiveModelGateway._raise_for_error(response)

    assert captured.value.code == "MODEL_QUOTA_EXHAUSTED"
    assert captured.value.retryable is False
