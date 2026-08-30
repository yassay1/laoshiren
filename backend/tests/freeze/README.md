# Backend Freeze Gates

Executable subsets of the V2.2 Backend Freeze Gates (architecture §19).

| Marker | Gate | Scope in this repo |
|--------|------|-------------------|
| `gate_a` | User journey (live) | `evals/test_live_agent_scenarios.py`（`RUN_MODEL_EVALS=1`） |
| `gate_b` | Safety & consistency | Version conflict, memory authority, UNKNOWN_OUTCOME |
| `gate_c` | Resilience | Durable job lease recovery, Redis fail-open |
| `gate_d` | Agent quality | `tests/evals` E01–E15（`not live_model`） |

## Run locally

```powershell
cd backend
$env:RUN_DATABASE_TESTS='1'
uv run python scripts/run_freeze_gates.py
```

Release checklist: [docs/RELEASE_FREEZE_GATES.md](../../docs/RELEASE_FREEZE_GATES.md)

Gate A（可选，消耗模型配额）：

```powershell
$env:RUN_MODEL_EVALS='1'
uv run pytest evals -m "gate_a and live_model" -q
```
