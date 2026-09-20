# 当前实现（Backend V2.2）

更新时间：2026-09-20。本文件只描述仓库当前真实代码；V2.2 目标与 Deferred 能力不写成现状。

## 当前可运行能力

- FastAPI 模块化单体，依赖方向 Presentation/Agent/Worker → Application → Domain；Infrastructure 实现 ports。
- PostgreSQL/pgvector + Alembic，**head `20260920_0043`**；受管表 `alembic check` 已接入 CI，LangGraph checkpoint 由框架 lifecycle 管理。
- **Personal State**：Thing/Task/ThingDate/ThingContextEntry/Blocker、merge redirect、recurring Task、delete tombstone、21 个 semantic write capability、Overview/Today/Attention 读模型。
- **File（Phase 4）**：files/generations/retrieval_segments/web_observations/message_attachments；两阶段 `FILE_PURGE`；orphan storage scan。
- **Runtime（Phase 2）**：Thread/Message/Run、RunEvent sequence、RunInteraction/HITL、DurableJob、ToolExecution ledger、budget snapshot、SSE replay + Redis wake-up/ephemeral frame。
- **Agent**：Single Executive LangGraph、冻结 21 capability Tool Registry、Policy、DeepSeek/智谱 Gateway + retry/failover。
- **Memory（Phase 5）**：PROFILE/SEMANTIC/EPISODIC、RRF hybrid search、forget suppression、durable `MEMORY_FORMATION` worker、State reconciliation on formation。
- **Automation（Phase 6）**：Occurrence materialize → `AUTOMATION_OCCURRENCE` worker → NotificationIntent → `PUSH_DELIVERY` worker；Occurrence、通知与 Job 原子结算，失败后有界重试和租约恢复；一次性物化后清空 `next_trigger_at`；PushEndpoint 表；legacy `notification_outbox` 仍可读/测试。
- **Identity（Phase 7）**：Huawei login stub、Business Session、Device/Push API、`ACCOUNT_DELETION` worker、开发 Bearer 回退、Redis rate limit（fail-open）。
- **Contracts**：`contracts/openapi.json`、`tool-registry.json`、agent-stream/context-manifest JSON Schema；CI drift check。
- **Freeze Gates（Phase 8）**：Gate B/C/D CI + Gate A live 手册；[RELEASE_FREEZE_GATES](docs/RELEASE_FREEZE_GATES.md)

## 部分实现与限制

- Huawei ID **生产 JWKS**、Huawei Push Kit、S3 Object Storage 未实现。
- 账号注销停用 Automation/Push/Session，**未**批量 purge 用户内容数据。
- Automation API/Tool 仍部分 legacy enum；RELATIVE/CONDITION 完整调度 Deferred。
- `notification_outbox` 表未删除。
- OpenTelemetry tracing、Gate A 默认 CI 未接入。
- HarmonyOS 客户端除 Chat/SSE 外完成度有限。

## 验证基线（2026-09-20）

- `uv sync --locked` / `ruff`：通过
- `RUN_DATABASE_TESTS=1` pytest `-m "not live_model"`：**224 passed**
- Alembic head：**`20260920_0043`**；已验证 upgrade → downgrade → upgrade
- `alembic check`：受管表无待生成升级操作；File ORM 纳入比较，框架管理的 checkpoint 表排除。

## 常用命令

```powershell
cd backend
uv run alembic upgrade head
uv run python scripts/export_openapi.py
uv run python scripts/run_freeze_gates.py
$env:RUN_DATABASE_TESTS='1'
uv run pytest -m "not live_model"
```
