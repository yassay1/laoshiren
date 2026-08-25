# Agent 状态感知与完整执行 —— 开发报告

日期：2026-08-25
提交：`b8216d7` feat: add agent state awareness and full execution tools

## 1. 目标

把单一 Executive Agent 从「只会录入 + 打勾」升级为「真正维护个人状态表」：能看（概览）、能深挖（读工具）、能完整执行（写/归档/自动化工具），并能主动检索长期记忆。

## 2. 完成的改动（按层）

| 层 | 文件 | 改动 |
|---|---|---|
| domain | `entities.py` | `Thing` 加 `archived_at` + `archive()`/`unarchive()`（幂等） |
| application | `dto.py` | 新增 `StateOverviewDTO` 及 4 个子 DTO |
| application | `service.py` | 新增 `get_state_overview`、`archive_thing`、`unarchive_thing` |
| application | `ports.py` | 补 repository 接口（概览聚合、归档） |
| application | `context.py` | `AgentContextBuilder` 增加 `state_overview` 槽位 + 预算裁剪 |
| application | `memories/context.py` | `AgentMemoryApplicationService.search` 语义检索 |
| agent | `tools.py` | 新增 14 个工具 + `register_automation_tools` + `register_memory_tools` + `build_tool_manifest` |
| agent | `model_gateway.py` | Protocol 增加 `tool_manifest` 参数 |
| agent | `graph.py` | 传入动态工具清单 |
| infra | `repositories/personal_state.py` | 归档写、`list_upcoming`/`list_active`/`list_recent`、`count_open`、`list_open`；修复 `archived_at` 死代码 |
| infra | `ai/deepseek.py` + `zhipu.py` | 系统提示改为动态模板，payload 携带 `state_overview` |
| workers | `agent.py` | Run 启动时计算概览并注入 |
| bootstrap | `bootstrap.py` | 注册 automation/memory 工具，注入 personal_state |

## 3. 工具清单（最终 22 个）

新增 14 个（括号为风险分级）：

- 读（READ）：`state.get_blockers`、`state.get_dates`、`state.get_relations`、`state.get_state_history`、`memory.search`
- 写（REVERSIBLE_WRITE）：`state.update_thing`、`state.transition_task`、`state.create_blocker`、`state.resolve_blocker`、`state.add_relation`、`automation.create`、`automation.change`
- 敏感写（SENSITIVE_WRITE，HITL）：`state.update_date`、`state.archive_thing`

叠加原有 8 个，共 22 个工具。HITL 确认路径从 1 条（`set_deadline`）增至 3 条（+`update_date` +`archive_thing`）。

## 4. 验证结果

| 检查 | 结果 |
|---|---|
| `ruff check src tests` | ✅ All checks passed |
| `mypy --strict src` | ✅ 105 source files, no issues |
| `pytest`（含集成，`RUN_DATABASE_TESTS=1`） | ✅ 84 passed |
| Docker / PostgreSQL | ✅ pgvector/pg17 容器健康，集成测试跑通 |

## 5. 自我反思与矫正

实现过程中发现并修正了设计稿与代码之间的偏差，以及若干冗余：

1. **`state.search_things` 冗余**：设计稿列了它，但现有 `state.list_things` 已支持关键词搜索，新增是重复。已去掉。
2. **automation 工具命名**：设计稿写 `state.create_automation`，但 automation 归 `AutomationApplicationService` 而非 PersonalState，改用 `automation.create`/`automation.change` 前缀，语义更准。
3. **active 状态集合**：设计稿写 `{ACTIVE, IN_PROGRESS}`，但 `ThingStatus` 无 `IN_PROGRESS`（那是 `TaskStatus`）。改为 `{ACTIVE, BLOCKED, WAITING}`。
4. **`UpcomingThingDTO` 去掉 `certainty`**：certainty 在 `ThingDate` 上，`Thing` 只有 `deadline_at` 投影，取它需额外 join `thing_dates`。概览是「小地图」，不值得为此加 join，去掉。
5. **测试 Fake Gateway 签名**：给 `decide` 增加 `tool_manifest` 参数后，4 个图测试 + 1 个 worker 测试的 Fake Gateway 需要同步适配。
6. **`archived_at` 死代码修复**：原 `list_for_user` 有 `archived_at IS NULL` 过滤但无写入路径；补上 Domain 字段、`add`/`update` 写路径后，该过滤从「死代码」变成「生效」。

## 6. 尚未完成 / 风险（诚实说明）

1. **真实模型 eval 未跑**：DeepSeek 凭据 401（沿用上一轮结论）。`automation` 与 `hitl` 场景现在有了对应工具，理论上可过，但未用真实模型验证。
2. **`memory.search` 语义检索依赖 embedding 配置**：未配置 `EMBEDDING_*` 时降级为关键词检索，语义能力未实测。
3. **概览是同步 prefetch**：每次 Run 启动做一次聚合查询，可能增加启动延迟；生产需实测并考虑缓存/异步。
4. **概览字符预算靠查询 limit**：`_trim_overview` 是粗粒度兜底，未做逐条目精细化裁剪。
5. **归档无 `unarchive` 工具**：只给了 `state.archive_thing`，恢复归档需走 Product API（`unarchive_thing` 用例已写好，未暴露为工具）。
6. **客户端未接新能力**：Today/Things 仍是空壳，本次纯后端。

## 7. 本次边界（明确不做）

- 不做 `upload_source`/`link_source` 工具（涉及文件二进制与 relevance 语义）。
- 不做自由写记忆工具（保持保守 formation，`memory.search` 只读）。
- 不做 procedural memory 演化、上下文分块顺序优化、主动搜记忆的 LLM 自动形成。
- 认证、客户端 Product 页不在本次范围。
