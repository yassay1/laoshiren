# Phase 2 Completion Plan

目标：完成 Backend V2.2 Runtime and Tool Contract Convergence，使 Run 在模型调用、checkpoint、Tool 副作用、HITL、终态 finalization、SSE 断线和进程崩溃下都能依据 durable facts 确定性恢复。

本计划只收敛 Runtime/Tool 基础契约。21 个语义业务 capability、Thing/Task 聚合重构属于 Phase 3；完整生产 Observability/Freeze Gates 属于 Phase 8。

## 已完成基线

- DurableJob AGENT_RUN 闭环、lease/heartbeat/fencing/recovery。
- RunInteraction/respond、WAITING_FOR_USER、Job pause/resume。
- stable action_id、Tool Ledger、receipt/error、UNKNOWN_OUTCOME。
- run_id checkpoint identity、严格 RunEvent sequence、SSE replay。
- Redis non-authoritative wake-up 与 PostgreSQL fallback。
- model/tool/active wall-time 硬预算。
- terminal output 先持久化及 crash 后无模型重入的 Product finalization。
- durable event 与 persisted delta/heartbeat 分离。

## P2.1 — Checkpoint Reconciliation Kernel

范围：建立 Application 可调用的 checkpoint inspection/reconciliation port；Worker claim 后先读取 Run、Job、Interaction、Tool Ledger 和 checkpoint durable facts，再决定继续 Graph、暂停、finalize 或失败。

实现要点：

- 定义 provider-neutral `CheckpointSnapshot`，只暴露 execution cursor、pending interrupt、pending stable actions、terminal output，不泄露 LangGraph 类型到 Application/Domain。
- 实现确定性矩阵：terminal checkpoint→finalize；interrupt checkpoint→创建/复用 Interaction 并 pause；WAITING 无 Interaction/checkpoint→RUNTIME_INCONSISTENCY；pending Tool action→走 Ledger replay/reconcile。
- accepted model step 以 checkpoint commit 为边界，不新增第二套权威 accepted-step 表。
- fault injection 覆盖 model response/checkpoint、checkpoint/Tool、interrupt/WAITING、terminal/finalization 四个 crash window。

验收：恢复路径不通过 LLM 猜状态；相同 durable facts 重复 reconcile 结果幂等；PostgreSQL 集成测试覆盖矩阵。

## P2.2 — Invocation-time Context Assembly

范围：把 Context Assembly 从“每 Run 一次预取”改为“每次 Executive invocation 重组”，checkpoint 只保存 run-scoped references、messages、Tool receipts 和计数。

实现要点：

- 定义 Application `ModelContextAssembler` port/DTO，并由 Worker adapter 加载最新 Personal State、Memory、File/Source、Attention。
- Executive node 每次调用 Gateway 前执行 assemble；Personal State 始终最后按 current reality 覆盖冲突 Memory。
- checkpoint 不保存全量 State/Memory、凭据或 provider payload。
- 增加 `ContextManifest`，记录使用的 source/memory/state refs、裁剪和预算结果，不记录 Chain-of-Thought。

验收：HITL resume 和多 Tool 循环能看到最新 State；State/Memory 冲突测试证明 State 胜出；checkpoint payload contract 测试通过。

## P2.3 — Complete Runtime Budget and Provider Policy

范围：在现有 model/tool/active wall-time 上限上补全 external action、search、input/output token 和可选 cost 计量；统一 retry/timeout/failover。

实现要点：

- 预算快照在 Run acceptance 时冻结，usage 持久化或可由 checkpoint/ledger 确定恢复。
- Gateway 返回 normalized usage；每次 invocation 前后原子校验预算，超限统一 BUDGET_EXHAUSTED。
- Model retry 只处理 retryable failure，使用 bounded exponential backoff+jitter；禁止 SDK 与 Runtime 双重隐式 retry。
- Provider failover 只允许发生在 accepted model step 之前；checkpoint 后不重新调用备用模型。
- WAITING_FOR_USER 继续不计 active runtime。

验收：边界值、恢复后累计、429/503、non-retryable 4xx、timeout、accepted 前/后 failover 测试通过。

## P2.4 — Tool Runtime Safety Closure

范围：完成通用 Tool Runtime envelope、内部 mutation/ledger 协调事务和外部 UNKNOWN_OUTCOME reconciliation；不在本阶段重写 21 个业务 capability。

实现要点：

- Tool 返回统一 `status/receipt/error/warnings/current_state` envelope；Executive 只依据 persisted receipt 回答。
- 为内部 PostgreSQL mutation提供同一 UoW 内写 business effect + StateMutation/Timeline + ledger receipt 的 binding 模式，并迁移至少一个代表性 mutation 证明边界。
- 外部 mutation 保存 provider idempotency/request id；定义 reconcile port，UNKNOWN_OUTCOME 禁止 blind retry。
- same action_id + different arguments hash 保持 invariant failure。
- Running cancel 先等待/收敛已开始的 external mutation，再停止未来动作；cancel 不宣称 rollback。

验收：成功 replay、deterministic failure replay、UNKNOWN_OUTCOME、stale fencing、cancel/in-flight external Tool contract tests 通过。

## P2.5 — Ephemeral Live Frames and SSE Race Closure

范围：提供不写 PostgreSQL的 `assistant.delta`、transport heartbeat、stream reset，并完成 replay-subscribe-catch-up。

实现要点：

- Durable RunEvent 与 EphemeralFrame 使用不同 DTO/Schema/Port。
- Redis 可传 ephemeral frame 和 durable wake-up，但断线丢失合法；客户端必须以 Snapshot+durable replay 收敛。
- SSE 顺序：subscribe→读取 PostgreSQL catch-up→live→周期性 PostgreSQL catch-up，消除 subscribe race。
- stream reset 明确要求客户端重新拉 Snapshot；heartbeat 仅为 SSE transport frame。

验收：delta 不落库；Redis down 时仅失去 live delta、不丢 durable fact；Last-Event-ID replay 和 subscribe race 测试通过。

## P2.6 — Runtime Contract Freeze

范围：集中完成 Phase 2 契约与回归门槛。

必须验证：

- migration 从当前受支持起点连续 upgrade，新增 migration 可 downgrade/upgrade。
- unit：Domain/Application、budget、retry、reconciliation、Tool envelope。
- integration：API、Repository、Tool→Application、checkpoint crash matrix、Redis outage。
- contract：OpenAPI、Tool Schema、SSE durable schema、EphemeralFrame schema、DB enum/index/unique constraints。
- eval：现有 deterministic eval 不退化；不把故障注入混入 Agent quality eval。
- 更新 CURRENT_IMPLEMENTATION、Gap List、Development Phases；Phase 2 只在所有门槛通过后标记 complete。

## 执行顺序与依赖

```text
P2.1 Reconciliation
  ├─→ P2.2 Context Assembly ─→ P2.3 Budget/Provider
  └─→ P2.4 Tool Safety

P2.1 + existing SSE ─→ P2.5 Ephemeral/Race

P2.2 + P2.3 + P2.4 + P2.5 ─→ P2.6 Freeze
```

建议按 P2.1→P2.2→P2.4→P2.3→P2.5→P2.6 实施。P2.1 先建立恢复事实模型；P2.4 先于 provider policy，可避免 retry/failover 绕过 Tool 安全边界。

## Phase 2 完成定义

只有同时满足以下条件才完成：

1. 所有 recovery 决策只依赖 PostgreSQL/checkpoint/ledger durable facts。
2. accepted model step、interrupt、Tool effect、terminal finalization 的 crash window 均有故障注入测试。
3. 每次 Executive invocation 使用最新 authoritative State 组装 Context。
4. Runtime budgets 和 provider retry/failover 是硬约束且跨恢复一致。
5. Tool replay/UNKNOWN_OUTCOME/cancel 语义完整，不发生 silent duplicate mutation。
6. Durable Event 与 EphemeralFrame 分离，Redis 故障不影响 durable correctness。
7. OpenAPI、Tool、SSE、DB contract drift 全部已审阅并固化。
