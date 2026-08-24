import pytest

from evals.scenarios import SCENARIOS, select_scenarios


def test_live_eval_catalog_covers_required_agent_behaviors() -> None:
    assert len(SCENARIOS) == 15
    assert {scenario.key for scenario in SCENARIOS} == {
        "direct_answer", "create_thing", "create_task", "complete_task", "multi_tool",
        "clarification", "hitl", "tool_failure", "memory_write", "profile_update",
        "memory_recall", "source_evidence", "automation", "long_thread",
        "ambiguous_language",
    }


def test_live_eval_selection_rejects_unknown_scenarios() -> None:
    with pytest.raises(ValueError, match="Unknown live eval"):
        select_scenarios("missing")
