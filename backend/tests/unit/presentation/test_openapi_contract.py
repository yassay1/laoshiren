import json
from pathlib import Path

REQUIRED_PATHS = (
    "/api/v1/health",
    "/api/v1/health/ready",
    "/api/v1/state/overview",
    "/api/v1/today",
    "/api/v1/things",
    "/api/v1/things/{thing_id}",
    "/api/v1/things/{thing_id}/archive",
    "/api/v1/things/{thing_id}/unarchive",
    "/api/v1/things/{thing_id}/dates",
    "/api/v1/things/{thing_id}/tasks",
    "/api/v1/sources",
    "/api/v1/sources/{source_id}",
    "/api/v1/memories",
    "/api/v1/automations",
    "/api/v1/attention",
    "/api/v1/threads",
    "/api/v1/runs",
    "/api/v1/runs/{run_id}/events",
)


def test_openapi_contract_includes_core_routes() -> None:
    root = Path(__file__).resolve().parents[4]
    contract = root / "contracts" / "openapi.json"
    if not contract.exists():
        raise AssertionError(
            "contracts/openapi.json is missing; run: uv run python scripts/export_openapi.py"
        )
    schema = json.loads(contract.read_text(encoding="utf-8"))
    paths = set(schema.get("paths", {}))
    missing = [path for path in REQUIRED_PATHS if path not in paths]
    assert not missing, f"OpenAPI contract missing routes: {missing}"
