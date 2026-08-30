# 老实人 Agent Runtime 技术设计

> **版本**：v2.2  
> **状态**：专项技术设计基线（Approved for Implementation Planning）  
> **适用阶段**：Backend V2 — Agent Runtime  
> **上位约束**：《老实人 Backend V2 总体架构设计 v2.2》  
> **更新时间**：2026-08-28  
> **性质**：Agent Runtime 运行时语义、可靠性边界与生产执行设计

---

# 0. 文档定位

本文定义“老实人” Backend V2 中 **一次 Agent Run 如何被接受、调度、执行、暂停、恢复、失败、取消、完成与重放**。

本文不是 LangGraph 教程，也不把整个后端设计成 Graph。

本文负责：Run / Durable Job / Interaction 生命周期；Worker claim / lease / heartbeat / fencing / recovery；LangGraph 在老实人 Runtime 中的职责；Executive / ToolRuntime 运行骨架；Checkpoint / interrupt / resume；Tool Execution Ledger 的 Runtime 语义；Context Assembly / ModelGateway / Runtime Budget；RunEvent / SSE / Redis live coordination；Retry / Timeout / Provider failover；Crash-window reconciliation；Runtime observability；Runtime Contract Freeze。

本文不负责最终 DDL、完整 Tool Schema、Application Use Case 业务字段、Memory 合并算法、File parser / chunk 参数、Automation Scheduler SQL、Huawei Push 请求参数、最终 API JSON 字段全集、Redis 具体 key 命名，以及 Lease / heartbeat / timeout 的最终数值。

本文使用：

- **MUST / 必须**：Runtime 架构不变量；
- **SHOULD / 应**：默认方案；
- **MAY / 可以**：实现选择。

---

# 1. Runtime 总目标

Agent Runtime 的目标不是“让 LangGraph 跑起来”，而是：

> **即使 HarmonyOS App 断网、SSE 断开、Redis 暂时不可用、Worker 崩溃、进程重启、Provider 超时或用户数小时后才确认，已经被后端接受的 Run 仍能以可恢复、可追踪、不可重复副作用的方式收敛到正确结果。**

生产级 Runtime 必须满足：

```text
accepted
→ durable
→ executable
→ observable
→ interruptible
→ resumable
→ recoverable
→ idempotent
→ reconcilable
```

---

# 2. Runtime 边界

## 2.1 Runtime 负责

```text
Run lifecycle
Durable dispatch
Worker ownership
Graph execution
Context assembly
Model invocation
Tool loop coordination
Policy/HITL coordination
Checkpoint
Interrupt/Resume
Tool execution safety
Run events
SSE replay
Runtime budget
Retry/timeout
Crash recovery
Observability
```

## 2.2 Runtime 不负责

```text
Thing 如何存
Task 业务规则
Memory 如何合并
File 如何 chunk
Automation 如何定义业务语义
Search 如何定义事实可信度
Personal State 的业务 invariant
```

这些由 Application / Domain / 对应专项模块负责。

---

# 3. 总体生产架构

```text
HarmonyOS
   │
   │ HTTPS / SSE
   ▼
┌────────────────────────────┐
│ FastAPI API                │
│                            │
│ auth / idempotency         │
│ create run                 │
│ run snapshot               │
│ SSE                        │
│ HITL response              │
└──────────────┬─────────────┘
               │
               ▼
┌────────────────────────────┐
│ PostgreSQL + pgvector      │
│                            │
│ Message                    │
│ Run                        │
│ RunEvent                   │
│ DurableJob                 │
│ RunInteraction             │
│ ToolExecutionLedger        │
│ LangGraph Checkpoint       │
└──────────────┬─────────────┘
               │
               │ durable truth
               │
        ┌──────┴──────┐
        │             │
        ▼             ▼
     Redis         Workers
 cache / pubsub    Agent Worker
 rate limit        Recovery
 wake-up           Scheduler...
        │             │
        └──────┬──────┘
               ▼
          LangGraph
        Executive
            ↕
        ToolRuntime
            │
            ▼
       Application
```

核心边界：

```text
PostgreSQL
= durable / authoritative runtime truth

Redis
= fast / ephemeral / non-authoritative coordination

LangGraph
= agent execution cursor / orchestration

Application
= durable business effect
```

Redis 故障允许造成性能或实时性下降，但不得造成 Run、Reminder、Checkpoint、Personal State、Memory、Tool 结果或 durable event 丢失。

---

# 4. 核心 Runtime 对象

## 4.1 Product Thread

```text
Thread
= Conversation Container
```

一个 Thread 可以包含多个 Run。Thread 不是 LangGraph checkpoint identity，也不是 Agent Graph State。

## 4.2 Run

```text
Run
= 一次 Agent Execution Lifecycle
```

Run 是客户端可观察的产品级执行对象。

## 4.3 Durable Job

```text
DurableJob
= “谁来执行这件事”的基础设施工作项
```

Run 与 Durable Job MUST 分离。Run 表达产品生命周期；Job 表达调度生命周期。File Processing、Memory Formation、Notification 等也可以复用同一 durable work 机制。

## 4.4 RunInteraction

```text
RunInteraction
= 一次需要用户响应的稳定 HITL 对象
```

它不是 LangGraph interrupt payload 的临时别名，而是可被移动客户端恢复、重试和幂等响应的一等 Runtime 对象。

## 4.5 RunEvent

```text
RunEvent
= Run 已发生过的 durable runtime fact
```

用于 SSE replay、客户端恢复、调试、审计和 crash reconciliation。

## 4.6 ToolExecution

```text
ToolExecution
= 一个稳定 RuntimeToolAction 的真实执行记录
```

承担 action identity、idempotent replay、persisted result、unknown outcome 和 reconciliation。

---

# 5. Run 接受语义

## 5.1 Run 接受与 Run 执行分离

`POST /runs` 成功不等于 Agent 已经执行完成。

Run 被认为“已接受”的条件是以下内容已在 **同一个 PostgreSQL transaction** 中持久化：

```text
USER Message
+
Run(QUEUED)
+
Initial RunEvent
+
DurableJob(READY)
```

推荐流程：

```text
POST /runs
   ↓
validate auth / thread / idempotency
   ↓
BEGIN
   ├─ create USER Message
   ├─ create Run(QUEUED)
   ├─ append run.queued
   └─ create DurableJob(AGENT_RUN, READY)
COMMIT
   ↓
best-effort Redis wake-up
   ↓
HTTP 201 / 202
```

## 5.2 Redis 不是 Run 接受条件

```text
DB COMMIT success
+
Redis publish failure
=
Run accepted
```

Worker 必须能够通过 PostgreSQL fallback polling 发现 READY Job。

## 5.3 Create Run 必须幂等

移动网络可能出现：

```text
Server commit success
↓
HTTP response lost
↓
client retry
```

因此 Create Run MUST 支持稳定 `Idempotency-Key`。

```text
(user_id, idempotency_key)
→ exactly one accepted logical request
```

相同 key + 相同 request：返回原 `run_id`。相同 key + 不同 request fingerprint：返回 `IDEMPOTENCY_CONFLICT`。

---

# 6. Run 状态机

Run 只保留少量产品级状态：

```text
QUEUED
RUNNING
WAITING_FOR_USER
COMPLETED
FAILED
CANCELLED
```

```text
QUEUED ───────────────→ RUNNING
                           │
               ┌───────────┼──────────────┐
               │           │              │
               ▼           ▼              ▼
     WAITING_FOR_USER   COMPLETED        FAILED
               │
               └────────────→ RUNNING

QUEUED / RUNNING / WAITING_FOR_USER
               │
               └────────────→ CANCELLED
```

以下不应成为 Run status：

```text
RETRYING
RECOVERING
STREAMING
MODEL_RUNNING
TOOL_RUNNING
FINALIZING
```

它们属于 RunEvent、Job 或 telemetry。

## 6.1 Terminal State immutable

`COMPLETED / FAILED / CANCELLED` 一旦进入，MUST 不再恢复为 RUNNING。

失败后重试创建新 Run：

```text
R001 FAILED
↓
R002 QUEUED
retry_of_run_id = R001
```

HITL Resume 是继续同一 Run 的正常路径。

## 6.2 Product Thread 并发限制

V2.2 MUST 限制：

> **一个 Product Thread 同时最多一个 non-terminal interactive Run。**

V2.2 不提前实现 concurrent chat runs、queued turns、agent steering 或 conversational branches。

---

# 7. Durable Job 状态机

Job 状态：

```text
READY
CLAIMED
PAUSED
COMPLETED
FAILED
CANCELLED
```

```text
READY ───────────→ CLAIMED
                     │
      lease expiry   │
      retry/backoff  │
          ┌──────────┘
          ▼
        READY

CLAIMED ─────────→ PAUSED
PAUSED ──────────→ READY

CLAIMED ─────────→ COMPLETED
CLAIMED ─────────→ FAILED

READY / CLAIMED / PAUSED
        └────────→ CANCELLED
```

`RETRYING` 不单独成为状态。Retry/backoff 表达为：

```text
status = READY
available_at = future
delivery_attempt += 1
```

---

# 8. Job Claim

多 Worker SHOULD 使用 PostgreSQL 原子领取：

```sql
SELECT ...
FOR UPDATE SKIP LOCKED
```

领取条件概念上：

```text
status = READY
available_at <= now()
```

排序必须稳定，例如：

```text
priority DESC
available_at ASC
created_at ASC
job_id ASC
```

Claim transaction MUST 保持很短：

```text
BEGIN
SELECT READY Job FOR UPDATE SKIP LOCKED
UPDATE Job → CLAIMED
UPDATE lease metadata
UPDATE Run → RUNNING when applicable
append run.started if first execution
COMMIT
```

LLM 与 Tool 执行发生在该事务之外。

---

# 9. Lease / Heartbeat / Fencing

## 9.1 Lease

Claim 后 Job 必须有：

```text
claimed_by
lease_until
```

长任务必须续租。Lease TTL / Heartbeat interval 属于运行参数，不在本文冻结具体数值。

## 9.2 claim_epoch / fencing token

仅有 lease 不足以阻止旧 Worker 恢复后继续写。

每次 claim：

```text
claim_epoch += 1
```

Worker 对关键 Runtime 写入必须验证：

```text
job_id
claimed_by
claim_epoch
```

如果 affected rows = 0：

```text
Worker has lost ownership
```

必须停止提交结果。

## 9.3 Heartbeat

Heartbeat MUST 独立于慢模型或慢 Tool：

```text
Worker
├─ graph execution coroutine
└─ lease heartbeat coroutine
```

进入 `WAITING_FOR_USER` 后：

```text
Job = PAUSED
clear lease
stop heartbeat
```

---

# 10. Worker Recovery

Recovery Scanner 周期检查：

```text
status = CLAIMED
AND lease_until < now()
```

典型收敛：

```text
expired CLAIMED
→ READY
available_at = backoff time
clear worker / lease
```

下一次 claim 递增 `claim_epoch`。

Worker crash / reclaim 属于 Infrastructure Recovery，Run 可以持续保持 `RUNNING`，因为 Run 表达产品执行生命周期，Job 表达基础设施调度状态。

---

# 11. LangGraph 的职责

LangGraph 只承担：

```text
agent orchestration
working state
checkpoint
interrupt
resume
durable execution cursor
streaming integration
```

必须保持：

```text
LangGraph State
≠ Personal State
≠ Long-term Memory
≠ Product Thread
```

---

# 12. LangGraph execution identity

V2.2 MUST 使用：

```text
LangGraph configurable.thread_id
= 老实人 run_id
```

而不是 Product Thread ID。

```text
Product Thread T001
├─ Run R001 → LangGraph thread_id = R001
├─ Run R002 → LangGraph thread_id = R002
└─ Run R003 → LangGraph thread_id = R003
```

因此：

```text
New Run
= new graph state

HITL Resume
= same run_id / same checkpoint identity
```

---

# 13. Minimal Graph

V2.2 SHOULD 保持最小拓扑：

```text
START
  ↓
EXECUTIVE
  │
  ├─ Final Answer → END
  │
  └─ Tool Actions
         ↓
    TOOL_RUNTIME
         │
         └────────→ EXECUTIVE
```

核心 Node：

```text
ExecutiveNode
ToolRuntimeNode
```

不应为了“图看起来完整”机械增加：

```text
load_context
memory_node
thing_resolver
policy_node
save_message
finalize_run
redis_publish
```

这些属于 Runtime component / Application / Infrastructure。

---

# 14. Graph State

Graph State 只保存 **恢复本次 Agent Execution 所需的 working state**。

概念上可包括：

```text
run_id
product_thread_id
current_message_id

runtime_messages
current_tool_actions
tool_results
turn_attachment_refs

model_step_count
tool_action_count

runtime_flags
final_output?
```

Graph State MUST NOT 保存：

```text
Personal State 全量快照
所有 Thing / Task
所有 Memory
文件 bytes / base64
PDF 全文
完整历史 Thread
Auth token
Push token
ORM Entity
Provider credentials
Chain-of-Thought
```

Checkpoint 是 Agent 工作现场；Personal State 是当前现实。

---

# 15. Accepted Model Step

一次模型返回只有在：

```text
Model Response
↓
Normalize
↓
stable RuntimeToolAction / final output
↓
Graph state update
↓
LangGraph checkpoint success
```

以后，才成为 `Accepted Model Step`。

语义：

- checkpoint 前 crash：允许重新调用模型；
- checkpoint 后 crash：必须继续 checkpoint 中的稳定 Action；
- 不得因为 recovery 再让模型“重新想一次”。

---

# 16. ExecutiveNode

ExecutiveNode 职责：

```text
check runtime budget
↓
ModelContextAssembler
↓
ModelGateway
↓
NormalizedModelResponse
↓
state update
```

ExecutiveNode 不直接 UPDATE 业务表、不直接访问 ORM、不直接调用 Huawei Push、不直接执行外部副作用。所有现实动作通过 Tool。

---

# 17. ModelContextAssembler

## 17.1 每次 Executive invocation 重新组装

Context 不只在 Run 开头加载一次。Tool 结果会变化；Personal State 可能被 UI / Automation 修改；HITL 可能等待数小时；Resume 后需要最新现实。

## 17.2 Initial Context

SHOULD 自动包含：

```text
System Instructions
Available Tools
current datetime
timezone
current user message
current attachments
recent messages
ThreadSummary
Tiny stable Profile
small relevant Thing Cards
```

## 17.3 Retrieved Context

按需进入：

```text
state.get_thing_context
memory.search
file.search
file.inspect
search.web
Exact URL Retrieval
other Tool Results
```

原则：

```text
fetch latest
≠
fetch everything
```

Thing Card 只是 candidate / navigation context。重要 mutation 前必须读取最新 authoritative State。

## 17.4 Assembler 不做业务推理

Assembler 只负责：

```text
fetch
select
budget
format
multimodal assembly
provider adaptation
```

不负责判断用户指的是哪个 Thing、不负责判断 Memory 谁对，也不决定是否创建 Task。

---

# 18. ContextManifest

V2.2 SHOULD 为每次 Model Invocation 保存轻量 ContextManifest。

概念字段：

```text
model_invocation_id
run_id
current_message_id

included:
  thing_ids + versions
  memory_ids
  file_ids
  message range
  thread_summary_version
  tool_result_ids

token_estimate
provider
model
```

生产默认不保存完整 Prompt 副本。

目的：可调试、可解释“当时模型看到了什么”、降低敏感数据复制、支持 Context Eval。

---

# 19. ModelGateway

## 19.1 Provider-neutral

```text
ModelRequest
→ ModelGateway
→ Provider Adapter
→ NormalizedModelResponse
```

业务 Runtime 不绑定 Provider 原始 payload。

## 19.2 Capability-aware

ModelGateway MUST 能表达模型能力，例如：

```text
text_input
image_input
document_input
audio_input
tool_calling
parallel_tool_calls
structured_output
streaming
context capability
provider file capability
```

不能把所有 Provider 强行压成最低公分母。

## 19.3 ModelRequest

概念上：

```text
instructions
messages
multimodal_parts
tools
response_constraints
stream
timeout
metadata
```

## 19.4 NormalizedModelResponse

概念上：

```text
model_invocation_id
content
tool_actions[]
finish_reason
usage
provider_metadata
```

---

# 20. RuntimeToolAction

Provider tool call 不能直接成为内部执行身份。

必须 Normalize 为稳定对象：

```text
RuntimeToolAction

action_id
tool_name
arguments

provider_call_id?
model_step
ordinal
```

`action_id` 必须在 Tool Execution 前稳定并 checkpoint，否则 crash replay 无法命中 Tool Ledger。

---

# 21. ToolRuntimeNode

ToolRuntimeNode 是生产 Tool execution pipeline：

```text
RuntimeToolAction
↓
ToolRegistry
↓
Schema Validation
↓
Authorization
↓
Policy
↓
┌───────────────┐
│ ALLOW / DENY  │
│ CONFIRM       │
└──────┬────────┘
       ↓
Tool Execution Ledger
       ↓
Application Use Case
       ↓
Persisted Receipt
       ↓
ToolResult
```

Agent Tool 不得直接访问 ORM、Repository、SQL 或外部凭据。

---

# 22. 多 Tool Action 执行规则

Read-only、独立 Tool MAY 并行。

Mutating / external side-effect Tool 默认顺序执行，不并行写。

如果 Write 参数依赖 Read 结果：

```text
Executive
↓
Read Tool
↓
Tool Result
↓
Executive
↓
Write Tool
```

不能把同一次 Model Response 中的 Read + Write 假装成顺序因果。

---

# 23. Tool Execution Ledger

概念字段：

```text
run_id
action_id
tool_name
arguments_hash
idempotency_key
status
persisted_result
replay_policy
unknown_outcome metadata
```

工程语义：

```text
at-least-once
+
idempotent replay
+
unknown-outcome protection
```

不宣称 exactly-once。

```text
same run_id + same action_id

SUCCESS
→ reuse persisted result

IN_PROGRESS
→ do not duplicate

UNKNOWN_OUTCOME
→ reconcile

NOT_FOUND
→ start execution
```

---

# 24. HITL / Interaction

Policy MUST 在副作用之前。

```text
Executive
↓
Proposed RuntimeToolAction
↓
Authorization / Policy
↓
requires confirmation?
   │
   YES
   ↓
interrupt
   ↓
user approval
   ↓
Tool Ledger
   ↓
Application
```

## 24.1 RunInteraction

概念：

```text
interaction_id
run_id
action_id
type
status
request_payload
response_payload?
created_at
resolved_at?
```

状态：

```text
PENDING
RESOLVED
CANCELLED
```

V2.2 MUST 限制：

```text
one Run
→ at most one PENDING Interaction
```

多个需要确认的 Action 按确定顺序一个一个形成 confirmation barrier。

---

# 25. Interrupt durability

正常顺序 MUST 是：

```text
LangGraph interrupt checkpoint durable
↓
Product Run → WAITING_FOR_USER
Job → PAUSED
Interaction durable
```

不能反过来，否则可能出现 Product Run 显示 WAITING，但没有任何 checkpoint 可以 resume。

---

# 26. HITL Resume

HarmonyOS 只提交用户决定：

```text
APPROVE
REJECT
clarification response
```

客户端不接触 LangGraph Command、checkpoint、Tool state 或 Graph state。

概念 API：

```text
POST /runs/{run_id}/interactions/{interaction_id}/respond
```

## 26.1 interaction response 幂等

同一 interaction：

```text
第一次 APPROVE
→ RESOLVED

重复相同 APPROVE
→ return existing resolution

相反 response
→ ALREADY_RESOLVED / conflict
```

## 26.2 Resume 不先改 Run=RUNNING

用户响应 transaction：

```text
Interaction = RESOLVED
Job PAUSED → READY
Run 仍 WAITING_FOR_USER
```

Worker 真正 claim：

```text
Run WAITING_FOR_USER → RUNNING
Job READY → CLAIMED
```

## 26.3 Approval 后重新验证现实

真正执行前必须重新验证：

```text
Authorization
Policy
Domain invariant
expected_version
current state
```

如果现实已经变化：返回 `VERSION_CONFLICT / STALE_ACTION`，交 Executive 重新判断。

---

# 27. Graph Completion 与 Product Completion

```text
Graph END
≠
Run COMPLETED
```

Graph terminal output 必须先 durable。

概念：

```text
final_output
execution = TERMINAL
```

进入 checkpoint 后，RunExecutor 才：

```text
BEGIN
create Assistant Message
Run → COMPLETED
Job → COMPLETED
append run.completed
COMMIT
```

如果 Graph END 后、finalization 前 crash：Recovery 读取 terminal checkpoint 并直接 finalize，不得重新调用模型。

---

# 28. Failure

Run 对外只使用 `FAILED`，但必须保存机器可识别的：

```text
failure_class
failure_code
```

Runtime 级 failure class 概念至少：

```text
PROVIDER_FAILURE
TOOL_FAILURE
UNKNOWN_OUTCOME
BUDGET_EXHAUSTED
RUNTIME_INCONSISTENCY
RECOVERY_EXHAUSTED
INTERNAL_ERROR
```

完整 Error Contract 在 API/Error 专项冻结。

---

# 29. Cancel

## 29.1 Queued / Waiting

```text
Run → CANCELLED
Job → CANCELLED
```

## 29.2 Running

采用 cooperative cancellation：

```text
cancel_requested_at = now()
```

Worker 在安全边界检查：

```text
before model call
after model call
before tool execution
after tool result
before next graph step
```

## 29.3 Cancel 不等于 rollback

> **Cancel 表示停止未来可停止的 Runtime Execution，不表示撤销已持久化副作用，也不表示忽略已经进入外部不可确定执行窗口的动作。**

若 mutating external Tool 正 in-flight，必须先收敛 SUCCESS / FAILURE / UNKNOWN_OUTCOME，再结束 Run。

---

# 30. Retry / Backoff

## 30.1 Provider Retryable

典型：network failure、read timeout、429、502/503/504、temporary provider unavailable。

允许：

```text
bounded retry
+
exponential backoff
+
jitter
```

## 30.2 Non-Retryable

典型：invalid credentials、permission denied、unsupported modality、invalid schema、bad request、context too large。

不得无意义重试。

## 30.3 Retry policy 统一由 ModelGateway 管理

避免 SDK retry 与 Runtime retry 隐式叠加。Provider SDK 自动 retry 必须关闭或明确纳入总重试预算。

---

# 31. Provider Failover

V2.2 MAY 支持有限 failover，但必须满足：

```text
current Model Step 尚未 durable accepted
+
fallback model capability-compatible
```

不得在已经 checkpoint 的 accepted decision 后重新换模型思考。

V2.2 不建设 complex intelligent routing、multi-model voting 或 difficulty-based auto routing。

第一阶段只需：

```text
primary
+
one configured compatible fallback
```

---

# 32. Runtime Budget

Runtime MUST 有硬预算，不依赖 Prompt 自律。

概念：

```text
RuntimeBudget
max_model_steps
max_tool_actions
max_external_actions
max_active_wall_time
max_input_tokens?
max_output_tokens?
max_search_calls?
max_estimated_cost?
```

不同 profile MAY 不同：

```text
INTERACTIVE
AUTOMATION
BACKGROUND
```

`WAITING_FOR_USER` 不计 active runtime。

Budget exhausted：Run → FAILED / `BUDGET_EXHAUSTED`，或在安全情况下产生受控 final response。

---

# 33. Model Streaming

```text
assistant.delta
= ephemeral presentation
```

不要求每个 token 持久化。

最终：

```text
Assistant Message
= durable product data
```

若 model invocation streaming 中途失败且未 accepted：

```text
discard incomplete generation
→ retry / fallback
```

客户端 live buffer 应按 `model_invocation_id / generation identity` 重置，不能把两次生成拼接。

---

# 34. RunEvent

每个 Run 使用严格递增 `sequence`，并应保证：

```text
UNIQUE(run_id, sequence)
```

概念字段：

```text
event_id
run_id
sequence
event_type
payload
visibility
schema_version
created_at
```

推荐 durable event 集：

```text
run.queued
run.started
assistant.started
assistant.completed
tool.started
tool.completed
tool.failed
hitl.requested
run.waiting_for_user
run.resumed
run.completed
run.failed
run.cancelled
```

LangGraph 原生 event MUST 经过 Runtime Event Mapper，不能直接成为 HarmonyOS Contract。

---

# 35. Durable Event 与 Ephemeral Frame 分离

```text
Durable:
Run state changes
Tool state changes
HITL
Terminal
Assistant completed

Ephemeral:
assistant.delta
transport heartbeat
stream reset
```

默认不把每个 token 写 PostgreSQL。

---

# 36. Redis Pub/Sub

Redis 只做：

```text
“某 Run 有新 durable event”
```

推荐 payload 只包含：

```text
run_id
latest_sequence
```

真正 Event 内容仍从 PostgreSQL 读取。

```text
Redis notification lost
≠
RunEvent lost
```

---

# 37. SSE

## 37.1 Run-scoped SSE

V2.2 SHOULD 使用：

```text
/runs/{run_id}/events
```

而不是 Thread 全局 stream。

## 37.2 SSE 不控制 Run

```text
SSE disconnected
≠
Run cancelled
```

手机锁屏、网络切换或 App 被杀时 Run 继续。

## 37.3 REST Snapshot + SSE Increment

客户端恢复：

```text
GET Run Snapshot
↓
if non-terminal
subscribe SSE
```

Run Snapshot 至少能表达：

```text
run_id
thread_id
status
last_event_sequence
pending_interaction?
timestamps
```

## 37.4 Replay

客户端使用 `Last-Event-ID`。

服务器：

```text
SELECT run_events
WHERE run_id = ?
AND sequence > ?
ORDER BY sequence
```

## 37.5 Replay / subscribe race

必须使用：

```text
Replay
↓
Subscribe Redis
↓
Catch-up DB query
↓
Live
```

SSE heartbeat 仅是 transport keepalive，不进入 RunEvent 表。

---

# 38. Run Snapshot 与 RunEvent

```text
Run row
= current runtime state snapshot

RunEvent
= how runtime got here
```

V2.2 不做完全 Event Sourcing，不要求仅通过 RunEvent 重建 Run row。

---

# 39. Unknown Outcome

最危险场景：

```text
external side effect succeeded?
↓
network timeout / crash
↓
ledger success not known
```

Runtime MUST 标记 `UNKNOWN_OUTCOME`。

处理方式依 Tool：provider idempotency key、查询外部状态、reconciliation、必要时人工处理。不得 generic blind retry。

内部 PostgreSQL Application mutation SHOULD 尽量把 business effect + Tool ledger receipt 放入可协调事务边界。

---

# 40. Crash Recovery Matrix

| Crash Window | Durable Fact | Recovery |
|---|---|---|
| Run transaction COMMIT 后、Redis publish 前 | Message / Run / Event / Job 已存在 | fallback polling |
| Worker claim 后、Graph 前 | Job CLAIMED + lease | lease expiry → reclaim |
| Model response 后、checkpoint 前 | 没有 accepted model step | 可重新调用模型 |
| checkpoint 后、Tool 前 | stable action_id | Tool Ledger replay |
| Tool effect 后、Ledger success 前 | 可能 UNKNOWN_OUTCOME | reconciliation，不盲 retry |
| interrupt checkpoint 后、Run WAITING 前 | checkpoint 有 pending interrupt | reconcile → WAITING / PAUSED / Interaction |
| Interaction resolved 后、Redis wake-up 前 | Interaction RESOLVED + Job READY | fallback polling |
| Graph terminal checkpoint 后、Product finalization 前 | final_output durable | 直接 finalize，不重新调模型 |
| Product finalization COMMIT 后、Redis publish 前 | Run COMPLETED / Assistant Message / Event durable | snapshot / replay |
| Running cancel 与 external mutating Tool in-flight | side effect 未收敛 | 先收敛 success/failure/unknown，再 cancel |

---

# 41. Recovery Reconciliation

三个 durable truth：

```text
Run
= product lifecycle truth

DurableJob
= work scheduling truth

LangGraph Checkpoint
= agent execution cursor truth
```

典型 reconciliation：

```text
Run = COMPLETED
Job = CLAIMED
→ Job → COMPLETED
```

```text
Run = RUNNING
Job expired
Checkpoint = INTERRUPTED
→ Run → WAITING_FOR_USER
→ Job → PAUSED
→ repair/create pending Interaction
```

```text
Run = RUNNING
Checkpoint = TERMINAL
→ Product Finalization
```

```text
Run = WAITING_FOR_USER
but no pending Interaction
and no interrupt checkpoint
→ RUNTIME_INCONSISTENCY
→ Run FAILED + operator-visible alert
```

核心原则：

> **Recovery 只根据已持久化事实做 deterministic reconciliation，不重新调用 LLM 猜 crash 前发生了什么。**

---

# 42. Job Retry Exhaustion

Durable Job MUST 有：

```text
delivery_attempt
max_delivery_attempts
```

超过最大次数：

```text
Job → FAILED
Run → FAILED
failure_class = RECOVERY_EXHAUSTED
```

V2.2 不引入 Kafka DLQ。FAILED durable_jobs 即可作为运维 dead-job view。

---

# 43. Security Boundary

Runtime 必须确保：

- API 从认证上下文获得 internal user_id；
- 客户端不能提交任意 user_id 控制 owner；
- Run / Thread / Interaction / SSE 都 owner-scoped；
- Tool Runtime 再做 authorization；
- HITL approval 不 bypass authorization；
- Provider credentials 只在服务端；
- Auth token / API key / Push token 不进入 Graph State；
- Tool argument / result 不默认完整暴露给客户端。

---

# 44. Client-visible Tool Event

SSE 不直接发送完整内部 Tool arguments / result。

建议只发送 `public_payload`，例如：

```text
tool_category = web_search
display = 正在查询网页
```

内部 observability 记录：

```text
tool_name
action_id
latency
arguments_hash
status
```

---

# 45. Observability

V2.2 **不引入 LangSmith**。

Production Observability 使用：

```text
Structured Logging
+
Metrics
+
OpenTelemetry Tracing
```

Observability failure MUST 不改变 Runtime 业务结果。

## 45.1 Trace

```text
Run Trace
├─ API accept
├─ Job claim
├─ Context assembly
├─ Model invocation
├─ Tool action
│  └─ Application use case
├─ External provider call
└─ Product finalization
```

## 45.2 Runtime IDs

按上下文传播：

```text
trace_id
user_id
thread_id
run_id
job_id
model_invocation_id
action_id
tool_execution_id
interaction_id?
```

## 45.3 Metrics

Run：

```text
run_accept_latency
queue_wait_time
active_run_duration
run_completion_rate
run_failure_rate
recovery_count
```

Model：

```text
model_ttft
model_latency
input_tokens
output_tokens
model_steps_per_run
provider_retry
provider_fallback
provider_error_rate
```

Tool：

```text
tool_latency
tool_success_rate
tool_retry
unknown_outcome
policy_deny
hitl_rate
```

Worker：

```text
claim_latency
lease_expired
reclaim_count
heartbeat_failure
fallback_poll
```

SSE：

```text
active_sse
disconnect_count
replay_event_count
redis_wakeup_latency
stream_reset
```

Context：

```text
context_input_tokens
recent_message_tokens
state_tokens
memory_tokens
file_tokens
tool_result_tokens
context_truncation_count
```

## 45.4 Production log privacy

默认不记录：完整用户消息、完整文件内容、完整 Memory、完整 Prompt、Auth token、API key、Push token、Chain-of-Thought。

优先记录：ID、hash、length、type、status、latency、error_class。

---

# 46. Runtime Error Model

Runtime 需要统一区分：

```text
Transient Infrastructure Error
Deterministic Business Error
Policy / HITL
Unknown Outcome
Budget Exhaustion
Runtime Inconsistency
```

Business Error（如 VERSION_CONFLICT、NOT_FOUND、INVALID_STATE_TRANSITION）不直接视作 Worker crash，可以作为 ToolResult/Error 返回 Executive 重新读取和判断。

HITL 不是 Error，`WAITING_FOR_USER` 是正常 Runtime 状态。

---

# 47. Testing

## 47.1 Deterministic Tests

必须覆盖：

```text
Run state transition
Job state transition
Interaction lifecycle
Idempotency
Lease / fencing
Replay
Terminal immutability
per-thread concurrency
```

## 47.2 Integration Tests

覆盖：

```text
POST /runs transaction
Worker claim
checkpoint persistence
Tool Ledger replay
SSE replay
Redis outage fallback
Run finalization
```

## 47.3 Failure Injection

必须主动制造：

```text
Redis down
Worker kill
process restart
DB connection loss
LLM timeout
Tool timeout
provider 429 / 503
lease expiry
heartbeat failure
SSE disconnect
network retry
crash after checkpoint
crash before ledger success
crash after graph terminal
```

并验证 deterministic reconciliation。

## 47.4 Agent Eval

只评估 Executive semantic behavior、Tool selection、Thing resolution、HITL appropriateness、final answer quality；不要求固定 Tool trajectory。

---

# 48. V1 → V2.2 Runtime Migration

当前实现已有 Thread / Message / Run、LangGraph Executive、Tool / Policy、Checkpoint、SSE。

V2.2 不推倒重写。

目标迁移：

```text
InProcess Run Queue
→ PostgreSQL DurableJob

单 Worker 执行
→ claim / lease / fencing / recovery

Product Thread = Graph execution identity
→ run_id = LangGraph checkpoint identity

简单 Tool invoke
→ ToolRuntime + Ledger + Policy + HITL

SSE live-only
→ PostgreSQL RunEvent + replay + Redis wake-up

Run completion
→ terminal graph checkpoint + product finalization

fixed runtime logs
→ structured logs + metrics + OpenTelemetry
```

迁移必须保护 existing persisted Run、stable IDs、checkpoint compatibility where feasible、OpenAPI / SSE contract compatibility 和 deterministic tests。

---

# 49. Frozen Runtime Contracts

V2.2 Freeze 前必须固定以下语义。

## 49.1 Lifecycle

```text
Run states / transitions
Job states / transitions
Interaction states / transitions
Terminal immutability
```

## 49.2 Identity

```text
run_id
job_id
action_id
model_invocation_id
interaction_id
LangGraph checkpoint identity = run_id
```

## 49.3 Acceptance

```text
Message + Run + RunEvent + DurableJob
same DB transaction
```

## 49.4 Worker Ownership

```text
claim
lease
heartbeat
claim_epoch / fencing
reclaim
```

## 49.5 HITL

```text
checkpoint before Product WAITING
one unresolved interaction per Run
idempotent response
latest-state revalidation
```

## 49.6 Tool Replay

```text
stable action_id
Tool Ledger
persisted receipt
unknown outcome
```

## 49.7 Client Runtime

```text
idempotent Create Run
idempotent Interaction Response
idempotent Cancel
Run-scoped SSE
RunEvent sequence
Last-Event-ID replay
REST Snapshot + SSE increment
```

## 49.8 Recovery

```text
Redis failure = degradation
Worker reclaim
terminal graph finalization
deterministic reconciliation
```

---

# 50. Deferred Implementation Parameters

以下不在本技术设计冻结：

```text
lease TTL
heartbeat interval
claim batch size
poll interval
Redis channel naming
RunEvent retention days
max_model_steps concrete value
max_tool_actions concrete value
provider timeout
provider retry count
OpenTelemetry backend
sampling rate
DDL index name
JSON field naming details
```

这些必须通过 config、load test、failure injection、agent eval 和 production observation 后确定。

---

# 51. Runtime Architecture Decisions 摘要

本文形成的核心决定可以压缩为：

1. Run 接受与执行分离；
2. Run 与 Durable Job 分离；
3. PostgreSQL 是 durable work truth；
4. Redis 只做非权威 wake-up / coordination；
5. Worker 使用 claim + lease + fencing；
6. Worker crash 通过 deterministic recovery 收敛；
7. LangGraph checkpoint identity 使用 run_id；
8. Graph 保持 `Executive ↔ ToolRuntime` 最小拓扑；
9. Graph State 只保存 run-scoped working state；
10. Context 每次 Executive invocation 重新组装；
11. ModelContextAssembler 不做业务推理；
12. ModelGateway provider-neutral 且 capability-aware；
13. ToolCall 必须 Normalize 为稳定 RuntimeToolAction；
14. Accepted Model Step 以 checkpoint 成功为界；
15. Tool 通过 Registry / Validation / Authorization / Policy / Ledger / Application；
16. Read MAY 并行，mutation 默认顺序执行；
17. HITL 必须发生在副作用之前；
18. interrupt checkpoint 必须先于 Product WAITING；
19. 一个 Run 同时最多一个 unresolved Interaction；
20. HITL approval 后仍重新验证最新现实；
21. Graph END 与 Product Run COMPLETED 分离；
22. terminal graph output durable 后再 finalization；
23. Run terminal state immutable；
24. Retry failed Run 创建新 Run；
25. Running Cancel 为 cooperative cancellation；
26. Cancel 不等于 rollback；
27. unknown outcome 不盲 retry；
28. Create Run / Interaction Response / Cancel 必须幂等；
29. 一个 Product Thread 最多一个 active interactive Run；
30. RunEvent 使用 PostgreSQL + sequence；
31. Redis Pub/Sub 只做 live wake-up；
32. SSE 是观察通道，不控制 Run；
33. REST Snapshot + SSE incremental update；
34. Token delta 默认 ephemeral；
35. LangGraph 原生 event 不直接成为客户端 Contract；
36. Retry 只针对 transient error；
37. Provider failover 只发生在未 accepted model step；
38. Runtime Budget 必须有硬限制；
39. WAITING_FOR_USER 不计 active runtime；
40. Recovery 不通过重新调用 LLM 猜状态；
41. Production observability 使用 Structured Logs + Metrics + OpenTelemetry；
42. 不引入 LangSmith。

---

# 52. Backend V2.2 Runtime 一句话定义

> **老实人 Agent Runtime v2.2 是一个以 PostgreSQL 保存 Run / Job / Event / Checkpoint 的 durable truth、以 Redis 提供非权威实时协调、以 LangGraph 承担 Executive 与 ToolRuntime 的可恢复执行，并通过 Worker Lease、Tool Ledger、HITL、SSE Replay、Runtime Budget 与 deterministic reconciliation 保证 Agent 在移动端断线、进程崩溃和外部不确定性下仍能安全收敛的生产级运行时。**
