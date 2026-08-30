# Phase 3 Completion Plan

目标：完成 Backend V2.2 Personal State 与 Semantic Tool Surface，使 Agent 仅通过 21 个冻结 capability 读写当前现实（Personal State authority），并在 Tool ledger 下原子提交 mutation、receipt 与 audit。

本计划收敛 Thing/Task/ThingDate/ThingContextEntry/Blocker/merge/recurring Task 语义与 Agent Tool 面；File→File 迁移、Memory DurableJob、正式 Automation 模型属于后续 Phase。

## 已完成基线

- Thing lifecycle enums、archive/restore/complete/cancel、delete tombstone。
- ThingContextEntry 软状态、merge redirect（`state_get_thing_context` bundle 含 `requested_thing_id`/`resolved_thing_id`）。
- standalone Task、recurring Task、`task_change_status` 状态机。
- ThingDate typed write（CREATE/UPDATE）、DateCertainty/DatePrecision。
- Blocker open/resolve 统一 `blocker_manage`。
- 聚合读：`state_get_overview`、`state_get_thing_context`。
- 21 个 V2.2 capability 名称冻结；legacy `state.*`/`memory.*` 等 Agent handler 已移除。
- 全部 write capability 通过 `complete_mutation_tool` + 各域 `write_ops` 在同一 UoW 绑定 ledger receipt。
- `contracts/tool-registry.json` 契约快照与 registry freeze 测试。

## P3.1 — Personal State Domain Convergence

范围：Thing/Task/ThingDate/ThingContextEntry/Blocker/merge/recurring 的领域模型、repository 过滤与 optimistic concurrency。

验收：单元测试覆盖 lifecycle、merge redirect、context entry、recurring completion；integration 测试覆盖 Product API 与 service。

状态：**完成**

## P3.2 — Semantic Tool Surface (21 Capabilities)

范围：Agent Tool Registry 仅暴露设计冻结的 21 capability；读工具聚合、写工具语义化（`thing_date_set`/`blocker_manage`/`thing_change_state` 等）。

验收：`V2_2_CAPABILITY_NAMES` 与 registry 完全一致；policy/prompt 无 legacy 名称；eval scenario 使用新名称。

状态：**完成**

## P3.3 — Write Path Ledger Binding

范围：Personal State、Source、Memory、Automation 写路径提取 `write_ops`；Runtime `complete_mutation_tool` 通用绑定；Tool handler 在 claim 存在时走 bound mutation。

验收：integration 测试验证 receipt 持久化；graph/worker 不 double-complete；idempotency replay 保持 deterministic。

状态：**完成**

## P3.4 — Delete Tombstone and Merge Redirect

范围：Thing/Source soft delete；merge 后读路径 redirect；API `get_thing` 保留 `merged_into_thing_id`，agent context 路径 resolve canonical。

验收：migration 0035；merge API 与 agent prefetch 测试通过。

状态：**完成**

## P3.5 — Contract Freeze

范围：`contracts/tool-registry.json`、export 脚本、registry contract 测试；更新 CURRENT_IMPLEMENTATION 与 Gap List。

验收：CI 可检测 tool surface drift；文档标记 Phase 3 完成。

状态：**完成**

## 明确不在 Phase 3 的范围

- ThingRelation：保留为 Product API 遗留面；Agent 使用 `thing_merge`，不暴露通用 relation Tool。
- typed provenance/EvidenceRef：Phase 4 File/Evidence 迁移。
- Source→File 命名与 lifecycle：Phase 4。
- Memory commit-time reconciliation、DurableJob formation：Phase 5。

## Phase 3 Exit Criteria（全部满足）

1. Alembic head 包含 Personal State Phase 3 migrations（至 0035）。
2. 21 capability registry freeze 测试与 `contracts/tool-registry.json` 通过。
3. 全部 write capability 经 `write_ops` + ledger binding。
4. Agent `tools.py` 无未注册 legacy handler。
5. unit/evals 非 live_model 全绿；`RUN_DATABASE_TESTS=1` integration 全绿。
