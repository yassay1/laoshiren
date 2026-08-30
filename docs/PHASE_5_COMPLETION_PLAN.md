# Phase 5 Completion Plan

目标：完成 Backend V2.2 Memory Convergence——durable formation job、forget suppression、commit-time State reconciliation、lexical+vector RRF hybrid retrieval、Tiny Profile/State authority 标注。

设计权威：《老实人_Personal_State与Memory技术设计_v2.2.md》。

## P5.1 — Durable MEMORY_FORMATION Job

状态：**完成**

- `application/memories/formation.py`：`enqueue_memory_formation` + `event_from_job_payload`
- `workers/memory.py`：claim `MEMORY_FORMATION` durable job，显式 remember 仍走 `process()` 热路径
- `workers/agent.py`：后台 formation 改为 `enqueue_durable`

## P5.2 — Forget Suppression

状态：**完成**

- migration `20260830_0038_memory_suppressions.py`
- `memory_suppressions` tombstone + `memory_content_fingerprint`
- `apply_forget_memory` 写入 suppression；`apply_create_memory` 检查并拒绝复活

## P5.3 — State Reconciliation

状态：**完成**

- `application/memories/reconciliation.py`：commit 前加载 State fact snapshot
- `apply_create_memory`：`memory-reconcile` advisory lock + `MEMORY_STATE_DUPLICATE` 拒绝
- `MemoryManager` CREATE 走 `create_if_allowed`

## P5.4 — Hybrid Retrieval (RRF)

状态：**完成**

- `application/memories/retrieval.py`：`reciprocal_rank_fusion` + `hybrid_search_memories`
- `MemoryApplicationService.search`：query + embedding 同时存在时走 RRF
- `AgentMemoryApplicationService` 透传 hybrid search

## P5.5 — Context Authority

状态：**完成**

- `MemoryContext.as_prompt_data()` 增加 `authority: NON-AUTHORITATIVE LONG-TERM MEMORY`
- `AgentContextBuilder` 已有 `current_reality` authoritative 区块（Phase 0+）

## Phase 5 Exit Criteria（全部满足）

1. Background formation 使用 `MEMORY_FORMATION` DurableJob，不再依赖进程内队列。
2. Forget 后同内容 fingerprint 不能通过 formation 自动复活。
3. CREATE commit 前重新读取 Personal State，重复 current reality 的 candidate 被拒绝。
4. `memory.search` / context load 在 query+embedding 可用时使用 lexical+vector RRF。
5. Memory context 明确标注 non-authoritative。
6. 单元测试覆盖 RRF、reconciliation、formation worker durable enqueue。

## 明确 Deferred（Phase 6+）

- Background stale-memory hygiene job（§41）
- Cross-encoder reranker / RRF 参数 Eval 调优
- 模型辅助的通用 candidate 矛盾检测
