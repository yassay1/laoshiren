import pytest

from evals.scenarios import SCENARIOS, select_scenarios


def test_live_eval_catalog_covers_required_agent_behaviors() -> None:
    keys = {scenario.key for scenario in SCENARIOS}
    assert len(SCENARIOS) >= 15
    for required in (
        "direct_answer",
        "e01",
        "e03",
        "e09",
        "e12",
        "e13",
        "create_thing",
        "automation",
        "tool_failure",
    ):
        assert required in keys


def test_live_eval_selection_rejects_unknown_scenarios() -> None:
    with pytest.raises(ValueError, match="Unknown live eval"):
        select_scenarios("missing")
