# Backend Release Freeze Gates (V2.2)

架构设计 §19 的四类 Gate 在本仓库的可执行映射。发布前建议按顺序跑通 B → C → D；Gate A 为可选 live 烟测（消耗模型配额）。

## Gate B — Safety & Consistency

**必须通过（CI 已覆盖）**

- 版本冲突不 silent overwrite
- Memory 非权威、formation 拒绝 state-authority 内容
- 外部副作用 Tool `UNKNOWN_OUTCOME` 不盲目重放

```powershell
cd backend
$env:RUN_DATABASE_TESTS='1'
uv run pytest tests/freeze -m gate_b -q
```

## Gate C — Resilience

**必须通过（CI 已覆盖）**

- Durable job lease 过期后可 `requeue_expired` 并完成（账号注销、文件 purge）
- Redis rate limit fail-open
- 建议本地再跑：`test_runtime_recovery`、`test_redis_runtime_wakeup`

```powershell
uv run pytest tests/freeze -m gate_c -q
```

## Gate D — Agent Quality

**必须通过（CI 已覆盖，确定性 mock gateway）**

- PRD E01–E15 核心场景 catalog + 集成测试（`tests/evals`）

```powershell
uv run pytest tests/evals -m "gate_d and not live_model" -q
```

## Gate A — User Journey (Live)

**发布前推荐、CI 默认跳过（需真实模型 Key）**

GitHub Actions：手动 `workflow_dispatch`，勾选 **Run Gate A live model evals**，并配置仓库 secret `MODEL_API_KEY`。

```powershell
$env:RUN_DATABASE_TESTS='1'
$env:RUN_MODEL_EVALS='1'
uv run pytest evals -m "gate_a and live_model" -q
```

## 一键本地（B + C + D）

```powershell
cd backend
$env:RUN_DATABASE_TESTS='1'
uv run python scripts/run_freeze_gates.py
```

## 契约与可观测性检查

```powershell
uv run python scripts/export_openapi.py
uv run python scripts/export_tool_registry.py
uv run python scripts/check_contract_schemas.py
git diff --exit-code ../contracts/openapi.json ../contracts/tool-registry.json
curl -s http://127.0.0.1:8000/api/v1/health/metrics
```

## 明确 Deferred（不阻塞本 Gate 清单）

- OpenTelemetry 分布式 tracing（已有 Prometheus backlog + 请求 `duration_ms` 日志）
- Huawei Push / JWKS / 生产 Object Storage
- 账号全量数据 purge
- Automation legacy enum API 完全切到 ONCE/RELATIVE/CONDITION
