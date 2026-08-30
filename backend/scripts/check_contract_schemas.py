"""Verify frozen JSON Schema contracts match backend enums."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / "backend" / "src"
sys.path.insert(0, str(BACKEND_SRC))

from laoshiren.domain.runtime.entities import RunEventType  # noqa: E402

CONTRACTS = ROOT / "contracts"


def _load(name: str) -> dict[str, object]:
    path = CONTRACTS / name
    if not path.exists():
        raise SystemExit(f"Missing contract file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def check_agent_stream_events() -> None:
    schema = _load("agent-stream-events.schema.json")
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise SystemExit("agent-stream-events.schema.json: missing properties")
    event = properties.get("event")
    if not isinstance(event, dict):
        raise SystemExit("agent-stream-events.schema.json: missing event property")
    contract_values = set(event.get("enum", []))
    code_values = {member.value for member in RunEventType}
    missing_in_contract = sorted(code_values - contract_values)
    extra_in_contract = sorted(contract_values - code_values)
    if missing_in_contract or extra_in_contract:
        raise SystemExit(
            "RunEventType drift vs agent-stream-events.schema.json: "
            f"missing={missing_in_contract} extra={extra_in_contract}"
        )


def check_ephemeral_frames() -> None:
    schema = _load("agent-ephemeral-frame.schema.json")
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise SystemExit("agent-ephemeral-frame.schema.json: missing properties")
    frame_type = properties.get("frame_type")
    if not isinstance(frame_type, dict):
        raise SystemExit("agent-ephemeral-frame.schema.json: missing frame_type")
    expected = {"assistant.delta", "stream.reset"}
    contract_values = set(frame_type.get("enum", []))
    if contract_values != expected:
        raise SystemExit(
            f"Ephemeral frame contract drift: expected {expected}, got {contract_values}"
        )


def check_context_manifest() -> None:
    schema = _load("context-manifest.schema.json")
    required = schema.get("required")
    if not isinstance(required, list):
        raise SystemExit("context-manifest.schema.json: missing required array")
    must_have = {
        "model_invocation_id",
        "run_id",
        "included",
        "token_estimate",
        "source_refs",
        "state_authority",
        "decision_index",
    }
    missing = must_have - set(required)
    if missing:
        raise SystemExit(f"context-manifest.schema.json missing required fields: {sorted(missing)}")


def main() -> None:
    check_agent_stream_events()
    check_ephemeral_frames()
    check_context_manifest()
    print("Contract schema checks passed.")


if __name__ == "__main__":
    main()
