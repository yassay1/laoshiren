# Agent 状态感知与完整执行 —— 设计文档

日期：2026-08-25
状态：已定稿，进入实现

## 1. 目标

让单一 Executive Agent 从"只会录入 + 打勾"升级为"真正维护个人状态表"：

1. **能看**：每次 Run 启动注入一份有界的个人事务表概览（state_overview）。
2. **能深挖**：补齐读工具，让 Agent 按需查询状态表细节与记忆。
3. **能完整执行**：补齐写工具，覆盖状态表的主要维护动作（编辑、阻塞、关系、归档、自动化）。

## 2. 定稿决策

| 决策点 | 结论 |
|---|---|
| 概览字段与预算 | `upcoming`(未来7天,最多8) / `blocked`(最多5) / `active`(最多8) / `recent`(最多5)，总预算 2–3k 字符 |
| 工具范围 | 6 读 + 7 写 + 3 敏感写（清单见 §5），不加不减 |
| archive_thing 分级 | `SENSITIVE_WRITE`，需 HITL 确认 |
| 概览性质 | 只读投影，Agent 改状态表后概览随之自动更新，不提供"编辑概览"能力 |
| 记忆工具 | 加 `memory.search`（只读）；写记忆仍走现有保守 formation，不放自由写 |

## 3. 两个贯穿全程的设计边界

1. **概览只读投影**：`state_overview` 是状态表现算的快照，Agent 只能改状态表，概览自动随之更新。规避 MemGPT/Letta 的"core memory 被 agent 写坏"翻车点。
2. **记忆只读**：`memory.search` 只读；记忆写入保留确定性候选 + 置信度门槛（`form_from_user_input`），不引入自由写记忆工具。

## 4. 架构与改动清单

沿用现有分层（Presentation/Agent/Worker → Application → Domain，Infrastructure 实现 ports），改动如下：

| 层 | 文件 | 改动 |
|---|---|---|
| domain | `domain/personal_state/entities.py` | `Thing` 加 `archived_at` + `archive()`/`unarchive()` |
| application | `application/personal_state/dto.py` | 新增 `StateOverviewDTO` |
| application | `application/personal_state/service.py` | 新增 `get_state_overview`、`archive_thing`、`unarchive_thing` |
| application | `application/personal_state/ports.py` | 补 repository 接口（归档、概览聚合查询） |
| application | `application/context.py` | `AgentContextBuilder` 增加 `state_overview` 槽位 |
| agent | `agent/tools.py` | 新增工具 + `register_memory_tools` |
| agent | `agent/tool_descriptions.py`（新） | 工具简介从 `ToolDefinition.description` 动态生成 |
| infra | `repositories/personal_state.py` | 归档写、`list_upcoming`、`list_active_blockers`、概览聚合 |
| infra | `ai/deepseek.py` + `zhipu.py` | `_SYSTEM_PROMPT` 工具说明改为动态生成 |
| bootstrap | `bootstrap.py` | 组装概览、注册 memory 工具 |

## 5. 工具清单与风险分级

沿用 `ToolRisk` + `ToolReplayPolicy`。

**读（READ / READ_ONLY）**
- `state.get_blockers`、`state.get_dates`、`state.get_relations`、`state.get_state_history`
- `memory.search`

**写（REVERSIBLE_WRITE / IDEMPOTENT）**
- `state.update_thing`、`state.transition_task`、`state.create_blocker`、`state.resolve_blocker`、`state.add_relation`
- `automation.create`、`automation.change`

**敏感写（SENSITIVE_WRITE，需 HITL）**
- `state.set_deadline`（已有）、`state.update_date`、`state.archive_thing`

> 实现矫正：`state.search_things` 未新增（`state.list_things` 已覆盖关键词搜索）；automation 工具命名从 `state.*` 改为 `automation.*`（归属 AutomationApplicationService 而非 PersonalState）；`active` 概览状态集合为 `{ACTIVE, BLOCKED, WAITING}`（ThingStatus 无 IN_PROGRESS）。

## 6. 数据流

```
Run 启动 → get_state_overview 现算快照 → AgentContextBuilder 注入 prefetched_state
        → gateway payload 携带 state_overview → Executive 决策
        → 工具调用（深挖/写/记忆）→ Application 用例 → 落库
```

## 7. 错误处理

新增工具复用 `ToolRegistry.execute` 的统一捕获：`EntityNotFound → NOT_FOUND`、`VersionConflict → CONFLICT`、`InvalidStateTransition → CONFLICT`、`KeyError/TypeError/ValueError → INVALID_ARGUMENT`。归档/写工具全部走 StateMutation 幂等（`idempotency_key` 由 `agent:run_id:action_id` 稳定导出）。

## 8. 测试策略

- **unit**：Thing 归档状态机、概览构建器预算与排序、新工具 adapter（参数/幂等 key/风险分级）、动态工具简介、memory.search。
- **integration**（标 `database`）：归档乐观并发/幂等、概览聚合 SQL、新工具走 Tool→Application。
- **eval**：`automation` 与 `hitl`（归档）场景现在有对应工具，可真实通过。

## 9. 边界（本次不做）

- 不做 `upload_source` / `link_source` 工具（涉及文件二进制与 relevance 语义）。
- 不做自由写记忆工具（保持保守 formation）。
- 不做 procedural memory 演化、分块顺序优化、主动搜记忆的 LLM 自动形成。
- 认证、客户端 Product 页不在本次范围。
