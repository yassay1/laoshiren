from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from evals.acceptance import ACCEPTANCE_SCENARIOS, CORE_SCENARIO_CODES, ScenarioPhase
from laoshiren.agent.prompts import EXECUTIVE_SYSTEM_PROMPT, build_executive_user_payload
from laoshiren.agent.tools import ToolRegistry, register_source_tools
from laoshiren.application.automations.dto import AttentionCandidateDTO
from laoshiren.application.context import AgentContextBuilder, attention_to_prompt_data
from laoshiren.application.personal_state.dto import (
    StateOverviewDTO,
    ThingDTO,
)
from laoshiren.application.personal_state.prefetch import (
    ambiguous_thing_candidates,
)
from laoshiren.application.runtime.dto import MessageDTO
from laoshiren.domain.automations.entities import AttentionSubjectType
from laoshiren.domain.personal_state.value_objects import ThingStatus
from laoshiren.domain.runtime.entities import MessageRole
from laoshiren.domain.sources.entities import SourceRelationType

pytestmark = pytest.mark.gate_d


def test_all_core_acceptance_scenarios_are_cataloged() -> None:
    core = [item for item in ACCEPTANCE_SCENARIOS if item.phase is ScenarioPhase.CORE]
    assert {item.code for item in core} == CORE_SCENARIO_CODES
    assert "E01" in CORE_SCENARIO_CODES
    assert "E10" not in CORE_SCENARIO_CODES


def test_executive_prompt_covers_state_memory_and_attention_rules() -> None:
    assert "Personal State" in EXECUTIVE_SYSTEM_PROMPT
    assert "Memory" in EXECUTIVE_SYSTEM_PROMPT
    assert "attention_candidates" in EXECUTIVE_SYSTEM_PROMPT
    assert "CONFIRMED" in EXECUTIVE_SYSTEM_PROMPT


def test_executive_payload_includes_prefetch_fields() -> None:
    payload = build_executive_user_payload(
        state={
            "current_input": "hello",
            "messages": [],
            "prefetched_state": {
                "active_thing_context": {"match_status": "resolved"},
                "attention_candidates": [{"summary": "due soon"}],
            },
            "tool_results": [],
        },
        available_tools=("state_get_thing_context",),
    )
    assert payload["active_thing_context"]["match_status"] == "resolved"
    assert payload["attention_candidates"][0]["summary"] == "due soon"


def test_context_builder_injects_attention_and_active_thing() -> None:
    overview = StateOverviewDTO(upcoming=(), blocked=(), active=(), recent=())
    attention = (
        AttentionCandidateDTO(
            subject_type=AttentionSubjectType.TASK,
            subject_id=uuid4(),
            thing_id=uuid4(),
            candidate_type="deadline_soon",
            severity="HIGH",
            summary="Demo 今天截止",
            due_at=datetime.now(UTC),
            last_surfaced_at=None,
            next_eligible_at=None,
            acknowledged=False,
        ),
    )
    message = MessageDTO(
        id=uuid4(),
        thread_id=uuid4(),
        role=MessageRole.USER,
        content="你好",
        run_id=uuid4(),
        source_ids=[],
        metadata={},
        created_at=datetime.now(UTC),
    )
    context = AgentContextBuilder().build(
        messages=[message],
        state_overview=overview,
        active_thing_context={"match_status": "resolved", "thing": {"name": "搬家"}},
        attention=attention,
    )
    assert context.prefetched_state["active_thing_context"]["thing"]["name"] == "搬家"
    assert context.prefetched_state["attention_candidates"][0]["summary"] == "Demo 今天截止"


def test_attention_prompt_data_includes_cooling_fields() -> None:
    due = datetime.now(UTC)
    data = attention_to_prompt_data(
        AttentionCandidateDTO(
            subject_type=AttentionSubjectType.DEADLINE,
            subject_id=uuid4(),
            thing_id=uuid4(),
            candidate_type="deadline_soon",
            severity="HIGH",
            summary="提交材料",
            due_at=due,
            last_surfaced_at=due,
            next_eligible_at=due,
            acknowledged=False,
        )
    )
    assert data["next_eligible_at"] is not None
    assert data["subject_type"] == "DEADLINE"


def test_thing_prefetch_marks_ambiguous_candidates() -> None:
    things = [
        ThingDTO(
            id=uuid4(),
            user_id=uuid4(),
            name="Demo A",
            status=ThingStatus.ACTIVE,
            current_stage=None,
            deadline_at=None,
            merged_into_thing_id=None,
            deleted_at=None,
            version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
        ThingDTO(
            id=uuid4(),
            user_id=uuid4(),
            name="Demo B",
            status=ThingStatus.ACTIVE,
            current_stage=None,
            deadline_at=None,
            merged_into_thing_id=None,
            deleted_at=None,
            version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
    ]
    payload = ambiguous_thing_candidates(things)
    assert payload["match_status"] == "ambiguous"
    assert len(payload["candidates"]) == 2


def test_source_tools_are_registered() -> None:
    registry = ToolRegistry()
    register_source_tools(registry, service=MagicMock())
    names = set(registry.names())
    assert "file_search" in names
    assert "file_inspect" in names
    assert "file_delete" in names


def test_source_relation_type_supports_reference() -> None:
    assert SourceRelationType.REFERENCE.value == "REFERENCE"
