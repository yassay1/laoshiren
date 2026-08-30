# Phase 8 Completion Plan — Freeze and Resilience

**Status**: Core complete (2026-08-30). Alembic head unchanged: `20260830_0041`.

## Delivered

### Contract freeze
- `contracts/openapi.json` + CI drift（OpenAPI、tool-registry）
- `scripts/check_contract_schemas.py` — RunEventType / ephemeral frame / context-manifest
- `test_openapi_contract.py` REQUIRED_PATHS（含 identity、health/metrics）

### Backend Freeze Gates
| Gate | 实现 |
|------|------|
| B | `tests/freeze/test_gate_b_*` — version conflict、memory authority、UNKNOWN_OUTCOME |
| C | `tests/freeze/test_gate_c_*` — job lease recovery、rate limit fail-open |
| D | `tests/evals/*` + `gate_d` marker；CI 确定性集成 |
| A | `evals/test_live_agent_scenarios.py` + `gate_a`（`RUN_MODEL_EVALS=1`，手动/可选） |

- `scripts/run_freeze_gates.py`
- [RELEASE_FREEZE_GATES.md](./RELEASE_FREEZE_GATES.md)
- CI：`tests/freeze` + `tests/evals -m gate_d`

### Resilience
- `application/runtime/durable_job_claim.py` — 全部 durable workers + Agent Run claim

### Observability
- 请求日志 `duration_ms`
- `GET /health/metrics` — Prometheus `laoshiren_backlog` gauges
- Readiness `durable_jobs_ready`

### Documentation
- [PRIVACY_DATA_INVENTORY.md](./PRIVACY_DATA_INVENTORY.md)
- [CURRENT_IMPLEMENTATION.md](./CURRENT_IMPLEMENTATION.md)、[CURRENT_V2_2_GAP_LIST.md](./CURRENT_V2_2_GAP_LIST.md) 刷新

## Deferred（不阻塞 Phase 8 关闭）

- OpenTelemetry 全链路
- Gate A 默认 CI（模型配额）；可选 `workflow_dispatch` + `MODEL_API_KEY`
- 全 worker Push/Search/LLM failure injection 矩阵
- SSE schema 自动生成（现为 check-only）
- Phase 7 生产项：Huawei Push、JWKS、S3、账号数据 purge

## 验证基线

```powershell
cd backend
$env:RUN_DATABASE_TESTS='1'
uv run python scripts/run_freeze_gates.py
uv run pytest -m "not live_model" -q   # 210 passed @ 2026-08-30
```
