# Backend V2.2 Development Phases

按真实依赖关系渐进实施；每阶段都包含 migration、确定性测试、契约 drift 检查和 CURRENT_IMPLEMENTATION 更新。

**当前进度（2026-08-30）**：Phase 0–8 核心完成。后续为生产化 Deferred（见各 Phase Completion Plan 与 [CURRENT_V2_2_GAP_LIST.md](./CURRENT_V2_2_GAP_LIST.md)）。

## Phase 0 — Repository Baseline Alignment ✅

正式设计一致化、真实代码审计、README/AGENTS/CURRENT、Gap List、质量与契约基线。

## Phase 1 — Durable Work Foundation ✅

建立通用 DurableJob Domain/Application Port/PostgreSQL Adapter、状态机、claim/lease/fencing/retry/recovery 和 migration；先让 Run acceptance 原子创建 Job，并保留旧 dispatcher 作为 commit 后 wake-up 优化。

## Phase 2 — Runtime and Tool Contract Convergence ✅

RunInteraction、Run/Job 状态协调、accepted model step/finalization、ToolExecution 正式状态/receipt/error、runtime budget、严格 event sequence/SSE replay；再接 Redis non-authoritative wake-up。

## Phase 3 — Personal State and Semantic Tool Surface ✅

Thing/Task/ThingDate/ThingContextEntry/Blocker/merge/recurring Task 收敛，聚合 Read + semantic Write 的 21 capability，version/receipt/audit/derived effects。详见 [PHASE_3_COMPLETION_PLAN.md](./PHASE_3_COMPLETION_PLAN.md)。

## Phase 4 — File and Evidence Migration ✅

Source→File 的 Expand/Backfill/dual-read/switch；MessageAttachment、ProcessingGeneration、RetrievalSegment、WebObservation、typed EvidenceRef、delete/purge/orphan。详见 [PHASE_4_COMPLETION_PLAN.md](./PHASE_4_COMPLETION_PLAN.md)。

## Phase 5 — Memory Convergence ✅

MemoryManager reconciliation、forget suppression、durable formation job、lexical+vector hybrid/RRF、State authority tests。详见 [PHASE_5_COMPLETION_PLAN.md](./PHASE_5_COMPLETION_PLAN.md)。

## Phase 6 — Automation and Notification ✅

Occurrence、NotificationIntent/Delivery/PushEndpoint 管线；legacy outbox 收缩中。详见 [PHASE_6_COMPLETION_PLAN.md](./PHASE_6_COMPLETION_PLAN.md)。

## Phase 7 — Identity and Production Platform ✅

Huawei login stub、Business Session、Device/Push API、Redis rate limit、account deletion worker。详见 [PHASE_7_COMPLETION_PLAN.md](./PHASE_7_COMPLETION_PLAN.md)。

## Phase 8 — Freeze and Resilience ✅

OpenAPI/Tool/SSE schema drift CI、Freeze Gate B/C/D harness、resilience tests、`claim_ready_jobs`、Prometheus metrics、隐私清单、发布 Gate 文档。详见 [PHASE_8_COMPLETION_PLAN.md](./PHASE_8_COMPLETION_PLAN.md) 与 [RELEASE_FREEZE_GATES.md](./RELEASE_FREEZE_GATES.md)。
