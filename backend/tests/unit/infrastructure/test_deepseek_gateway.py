from uuid import uuid4

import pytest

from laoshiren.agent.contracts import DecisionKind
from laoshiren.agent.model_gateway import ModelGatewayError
from laoshiren.infrastructure.ai.deepseek import DeepSeekExecutiveModelGateway


def test_deepseek_gateway_parses_response_and_tool_decisions() -> None:
    response = DeepSeekExecutiveModelGateway._parse_decision(
        {"kind": "respond", "content": " 已收到 "}, available_tools=()
    )
    thing_id = str(uuid4())
    call = DeepSeekExecutiveModelGateway._parse_decision(
        {
            "kind": "call_tool",
            "tool_name": "state.get_thing",
            "tool_arguments": {"thing_id": thing_id},
        },
        available_tools=("state.get_thing",),
    )

    assert response.kind is DecisionKind.RESPOND
    assert response.content == "已收到"
    assert call.tool_arguments == {"thing_id": thing_id}


def test_deepseek_gateway_rejects_unknown_tool() -> None:
    with pytest.raises(ModelGatewayError) as captured:
        DeepSeekExecutiveModelGateway._parse_decision(
            {"kind": "call_tool", "tool_name": "system.shell"},
            available_tools=("state.get_thing",),
        )
    assert captured.value.code == "MODEL_INVALID_RESPONSE"
