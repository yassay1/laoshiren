"""Export OpenAPI schema for contract drift checks."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND / "src"))

from laoshiren.main import create_app  # noqa: E402


def main() -> None:
    app = create_app()
    schema = app.openapi()
    output = ROOT / "contracts" / "openapi.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
