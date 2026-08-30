"""Run Backend Freeze Gate test subsets."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _run_pytest(*, paths: list[str], marker: str, allow_live_model: bool = False) -> int:
    backend = Path(__file__).resolve().parents[1]
    final_marker = marker if allow_live_model else f"({marker}) and not live_model"
    command = [
        "uv",
        "run",
        "pytest",
        *paths,
        "-m",
        final_marker,
        "-q",
    ]
    print("Running:", " ".join(command))
    return subprocess.call(command, cwd=backend)


def main() -> int:
    gates = sys.argv[1:] or ["gate_b", "gate_c", "gate_d"]
    exit_code = 0
    safety_resilience = [gate for gate in gates if gate in {"gate_b", "gate_c"}]
    if safety_resilience:
        exit_code |= _run_pytest(
            paths=["tests/freeze"],
            marker=" or ".join(safety_resilience),
        )
    if "gate_d" in gates:
        exit_code |= _run_pytest(paths=["tests/evals"], marker="gate_d")
    if "gate_a" in gates:
        if os.getenv("RUN_MODEL_EVALS") != "1":
            print(
                "Gate A skipped: set RUN_MODEL_EVALS=1 and RUN_DATABASE_TESTS=1, then run:\n"
                "  uv run pytest evals -m 'gate_a and live_model' -q"
            )
        else:
            exit_code |= _run_pytest(
                paths=["evals"],
                marker="gate_a and live_model",
                allow_live_model=True,
            )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
