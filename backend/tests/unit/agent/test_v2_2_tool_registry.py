import json
from pathlib import Path
from unittest.mock import MagicMock

from laoshiren.agent.tools import (
    V2_2_CAPABILITY_NAMES,
    ToolRegistry,
    export_tool_registry_contract,
    register_automation_tools,
    register_memory_tools,
    register_personal_state_tools,
    register_search_tools,
    register_source_tools,
)


def _build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_personal_state_tools(registry, MagicMock())
    register_automation_tools(registry, MagicMock())
    register_source_tools(registry, MagicMock())
    register_memory_tools(registry, MagicMock(), MagicMock())
    register_search_tools(registry, MagicMock())
    return registry


def test_v2_2_registry_registers_exactly_21_capabilities() -> None:
    registry = _build_registry()
    assert frozenset(registry.names()) == V2_2_CAPABILITY_NAMES
    assert len(registry.names()) == 21


def test_tool_registry_contract_matches_snapshot() -> None:
    root = Path(__file__).resolve().parents[4]
    contract_path = root / "contracts" / "tool-registry.json"
    if not contract_path.exists():
        raise AssertionError(
            "contracts/tool-registry.json is missing; "
            "run: uv run python scripts/export_tool_registry.py"
        )
    expected = json.loads(contract_path.read_text(encoding="utf-8"))
    actual = export_tool_registry_contract(_build_registry())
    assert actual == expected
