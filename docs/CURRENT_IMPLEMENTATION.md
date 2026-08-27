# 当前实现与审核说明

更新时间：2026-08-27。本文件只描述仓库当前代码，不把七份 v1.0 设计目标误写成已完成功能。

## 1. 实际组成

- HarmonyOS：可编译安装的单 entry Stage Model 应用；Chat 已接后端，其他三个一级页面主要是展示壳（前端本阶段搁置）。
- Backend：Clean Architecture 风格模块化单体，业务域包含 Personal State、Source、Memory、Automation/Attention、Runtime。
- Agent：单一 Executive LangGraph，30 个 Tool（19 state + 2 automation + 3 memory + 4 source + 2 search），确定性 Policy、HITL、上下文预取、并行只读 `call_tools`。
- Persistence：PostgreSQL/pgvector 业务表 + LangGraph 独立 checkpoint 表；Source 原件使用本地文件适配器。
- Contracts：OpenAPI 快照和 SSE 事件 Schema；CI 校验 `contracts/openapi.json` 无漂移。
- Evals：`evals/acceptance.py` 映射 PRD E01–E15；`tests/evals/` 提供确定性验收测试。

## 2. 后端 V1 核心闭环（2026-08-27 增量）

### Agent 上下文

- **Relevant Prefetch**：`get_agent_thing_prefetch` — Thread.active_thing_id 或 query 匹配 Thing，注入 `active_thing_context`。
- **State Overview**：`get_state_overview` 注入 Agent；REST `GET /api/v1/state/overview`。
- **Attention**：`AttentionApplicationService.get_candidates` 注入 `attention_candidates`（含冷却字段）；Run 启动时对注入项记录 `SURFACED`。
- **Memory / Source 预取**：Run 启动时加载 memory_context、source_context（Run 附 source_ids 时）。
- **Executive Prompt**：统一 `agent/prompts.py`，覆盖 E03/E12/E13/E14 规则。

### Deadline Policy（Tool/API Policy P02）

- `state.set_deadline` 带 `source_id` 时可走 SOURCE_VERIFIED 路径。
- 无来源的 CONFIRMED primary deadline → Policy `REQUIRE_MORE_CONTEXT`（E03）。
- 覆盖已有 deadline 且带 source → `REQUIRE_CONFIRMATION`。
- Application `set_deadline` 写入 `ThingDate.source_id` 与 mutation metadata。

### Source Tools（Agent）

- `source.get`、`source.search_chunks`、`source.link_thing`、`source.list_for_thing`

### REST API 补齐

- `GET /api/v1/state/overview`
- `GET /api/v1/today` — attention + overdue/due_today/overview 聚合
- `POST /api/v1/things/{id}/archive`、`/unarchive`
- `POST /api/v1/things/{id}/dates`（含 `source_id`）

### Automation → Agent Run（2026-08-27）

- 到期 Automation 生成 Notification Outbox 后，`dispatch_pending` 会：
  1. 调用 `RuntimeAutomationRunTrigger` → `create_automation_run`（`RunTrigger.AUTOMATION`）
  2. 提交 Notification 到 Adapter（Recording，Push 仍后置）
- 每用户复用 `automation-inbox:{user_id}` Thread；Run 幂等键 `automation-run:{occurrence_key}`

### OpenAPI 契约

- `backend/scripts/export_openapi.py` 导出至 `contracts/openapi.json`
- CI：`export_openapi.py` + `git diff --exit-code contracts/openapi.json`
- `tests/unit/presentation/test_openapi_contract.py` 校验核心 V1 路由

## 3. 真实聊天执行链

1. `ChatViewModel.initialize` → `POST /threads`
2. `ChatViewModel.send` → `POST /runs`（QUEUED + USER Message）
3. `InProcessRunDispatcher` → `AgentRunWorker.run_once`
4. Worker 组装：messages + memory + sources + state_overview + active_thing + attention
5. LangGraph Executive → Tool → Application
6. 完成 → ASSISTANT Message + SSE events；可选 Memory Formation

## 4. Agent Tool 清单（28）

**Personal State (19)**：get/list/create/update/complete/transition/archive 等  
**Automation (2)**：create、change  
**Memory (3)**：search、remember、forget  
**Source (4)**：get、search_chunks、link_thing、list_for_thing  
**Search (2)**：web、official（默认 RecordingAdapter；`SEARCH_PROVIDER=tavily` + `SEARCH_API_KEY` 启用生产搜索）

## 5. PRD 验收用例状态

| 用例 | 状态 |
|------|------|
| E01 状态更新 | Tool + 集成测试 |
| E02 状态查询 | Overview + Prefetch 已注入 |
| E03 不确定 Deadline | **Policy + 集成测试** |
| E04 跨 Thread 记忆 | Memory 检索 + **集成测试** |
| E05/E06 Source 闭环 | Source Tools + **E05/E06 集成测试** |
| E07 Attention | 已注入 Agent 上下文（live eval） |
| E08 Attention 冷却 | **SURFACED 冷却 + 集成测试** |
| E09 Automation | Tool + Scheduler + Automation→Agent Run |
| E10 Push | **后置**（RecordingAdapter；Run 已可离线触发） |
| E11 并行 | **已实现**（`call_tools` + `asyncio.gather`；live eval 仍可选） |
| E12 Tool 失败 | Prompt 规则 + Eval 场景 |
| E13 歧义 | Prefetch ambiguous + 集成测试 |
| E14 Memory/State 边界 | Prompt + **集成测试** |
| E15 Source 保留 | 原件存储 + **集成测试** |

## 6. 仍存在的限制

1. 认证仅开发态固定 token
2. Push 未真实投递
3. HarmonyOS 产品页未接 API（前端搁置；后端已有 `/today` 读模型）
4. CONDITION_WATCH 仍为 stub（Scheduler 可复用 `SearchApplicationService`）
5. Specialist Subgraph / 并行 Tool 未实现
6. 本地需 PostgreSQL 才能跑 database 标记测试

## 7. 测试

```powershell
cd backend
uv run pytest tests/unit tests/evals -m "not live_model"
$env:RUN_DATABASE_TESTS='1'
uv run pytest -m "not live_model"
$env:RUN_MODEL_EVALS='1'
uv run pytest evals -m live_model
uv run python scripts/export_openapi.py
```
