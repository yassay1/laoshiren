"""Export the V2.2 Agent tool registry for contract drift checks."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND / "src"))

from laoshiren.agent.tools import (  # noqa: E402
    ToolRegistry,
    export_tool_registry_contract,
    register_automation_tools,
    register_memory_tools,
    register_personal_state_tools,
    register_search_tools,
    register_source_tools,
)


def build_contract_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_personal_state_tools(registry, MagicMock())
    register_automation_tools(registry, MagicMock())
    register_source_tools(registry, MagicMock())
    register_memory_tools(registry, MagicMock(), MagicMock())
    register_search_tools(registry, MagicMock())
    return registry


def main() -> None:
    registry = build_contract_registry()
    contract = export_tool_registry_contract(registry)
    output = ROOT / "contracts" / "tool-registry.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output} ({len(contract)} capabilities)")


if __name__ == "__main__":
    main()
