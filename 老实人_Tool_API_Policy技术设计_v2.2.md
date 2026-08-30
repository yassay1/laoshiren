# 老实人 Tool / API / Policy 技术设计 v2.2

> **文档状态：正式开发专项基线（Baseline）**  
> **版本：v2.2**  
> **适用范围：老实人 Backend V2.2**  
> **目标平台：准备正式上线 HarmonyOS App 的个人 Agent 后端**  
> **默认 Agent 架构：Single Executive + ToolRuntime**  
> **Durable Truth：PostgreSQL**  
> **Redis：non-authoritative cache / coordination / wake-up only**  
> **本文不包含：最终 SQL DDL、最终 OpenAPI JSON、最终 Prompt、File/Search 内部实现、Scheduler 内部实现**

---

# 0. 文档目的

本文正式冻结老实人 Backend V2.2 的：

```text
Application Use Case
≠
HTTP Product API
≠
Agent-visible Tool API
```

三层边界，以及：

- Tool Architecture；
- Tool Registry；
- Tool Naming；
- Tool Granularity；
- V2.2 推荐 Tool Set；
- Tool Input / Result / Error Contract；
- Dynamic Tool Availability；
- Authorization；
- deterministic Policy；
- HITL；
- expected_version；
- ToolExecution Ledger；
- action_id / idempotency / replay；
- UNKNOWN_OUTCOME；
- Client-visible Tool Progress；
- HarmonyOS Product API 能力边界；
- User Journey；
- Failure / Crash Matrix；
- Frozen Decisions；
- Deferred Details。

本专项核心问题：

> **Executive Agent 被允许通过哪些稳定能力，安全、可靠、可恢复地读取和改变老实人的现实世界？**

---

# 1. 上位设计约束

本文继承且不得随意推翻：

1. 《老实人_Backend_V2_总体架构设计_v2.2_正式基线版》
2. 《老实人_Agent_Runtime技术设计_v2.2》
3. 《老实人_上线最小用户与通知支持设计_v2.2》
4. 《老实人_Personal_State与Memory技术设计_v2.2》

尤其继承：

```text
Single Executive

LangGraph State
≠ Personal State
≠ Long-term Memory

LLM 有决策权
≠ 有授权权

Tool
→ Application Use Case
→ Domain / Repository / Infrastructure

at-least-once
+
idempotent replay
+
unknown-outcome protection

重要 mutation
→ version / expected_version

PostgreSQL
= durable truth

Redis
= non-authoritative coordination
```

---

# 2. V2.2 明确不做

本文不引入：

- 新 Agent Framework；
- MCP 作为项目架构；
- LangSmith；
- Tool Marketplace；
- 数据库驱动动态 Tool 插件系统；
- 每张表一组 CRUD Tool；
- `state.update_everything` 万能 Tool；
- Tool 直接访问 ORM / Repository / SQL；
- 企业级 IAM / RBAC；
- OPA / Drools / CEL 等复杂 Policy Engine；
- 另一个 LLM 做 Policy；
- Provider tool_call_id 作为内部 durable identity；
- Redis 作为 Tool Ledger truth；
- Chain-of-Thought 持久化；
- Generic Blind Retry；
- 所有 Write 都 HITL；
- 所有 Write 都自动执行；
- HTTP endpoint 自动注册为 Tool；
- Application Service 自动全部暴露给模型。

---

# 3. 总体 Tool Architecture

```text
                         Executive
                             │
                    Model Tool Call
                             │
                             ▼
                       ToolRuntime
                             │
      ┌──────────────────────┼───────────────────────┐
      ▼                      ▼                       ▼
 Tool Registry          Authorization             Policy
                                                     │
                                                   HITL?
                                                     │
                                                     ▼
                                            ToolExecution Ledger
                                                     │
                                                     ▼
                                           Application Binding
                                                     │
                                                     ▼
                                         Application Use Case
                                                     │
                              ┌──────────────────────┼───────────────────┐
                              ▼                      ▼                   ▼
                           Domain                Repository         Infrastructure
```

HarmonyOS 从另一条路径进入：

```text
HarmonyOS
   │
HTTP Product API
   │
Authentication / Authorization
   │
Application Use Case
   │
Domain / Repository / Infrastructure
```

因此：

```text
HTTP Product API
和
Agent Tool

是同级 Adapter
不是彼此的包装
```

---

# 4. 三层 Contract 正式边界

## 4.1 Application Use Case

Application Use Case 是后端真正允许发生的业务动作。

例如：

```text
CompleteTaskUseCase
CorrectThingDateUseCase
ArchiveThingUseCase
CreateTaskWithReminderUseCase
ForgetMemoryUseCase
DeleteThreadUseCase
```

它负责：

- Domain invariant；
- ownership scope；
- current state validation；
- expected_version；
- transaction boundary；
- durable mutation；
- derived effects；
- business receipt；
- audit / StateMutation；
- deterministic error。

它不关心调用方是：

```text
HarmonyOS
Agent
Automation Worker
Admin/Internal Job
```

---

## 4.2 HTTP Product API

HTTP Product API 面向 HarmonyOS 产品交互。

负责：

- Authentication；
- HTTP request parsing；
- path/query/body；
- multipart upload；
- pagination；
- ETag / expected_version representation；
- HTTP status；
- RFC 9457 Problem Details；
- UI-specific response DTO。

例如：

```text
POST /tasks/{task_id}/complete
→ CompleteTaskUseCase
```

HTTP Contract 服务 App，不服务模型。

---

## 4.3 Agent-visible Tool API

Agent Tool 是：

> **Executive 可理解、选择并调用的 model-facing capability。**

Agent Tool 负责表达：

```text
what it does
when to use
when not to use
required model-supplied arguments
side-effect semantics
structured result/error contract
```

它不负责：

- Authorization 最终决策；
- HITL 最终决策；
- SQL；
- ORM；
- Repository；
- Service Credential；
- client owner_user_id。

---

# 5. 为什么 HTTP API 不能自动注册成 Tool

HTTP 与 Agent Tool 优化目标不同。

HTTP 优化：

```text
UI completeness
forms
pagination
uploads
downloads
navigation
REST semantics
```

Tool 优化：

```text
model selection reliability
semantic clarity
low schema overlap
bounded context
safe execution
stable business meaning
```

例如 UI 可能需要：

```text
GET /tasks
GET /tasks/{id}
PATCH /tasks/{id}
POST /tasks/{id}/complete
DELETE /tasks/{id}
```

Executive 不应因此获得五个数据库式 Task Tool。

---

# 6. 为什么 Application Surface 大于 Tool Surface

内部 Application 未来可能拥有：

```text
RecomputeAttentionUseCase
CleanupOrphanFileUseCase
RebindMergedThingReferencesUseCase
ReconcileRelativeAutomationUseCase
RebuildThingCardUseCase
```

这些能力可以存在，但 Executive 没必要知道。

正式原则：

> **Application Capability Surface MUST 大于 Agent Tool Surface。**

---

# 7. Tool Architecture 方案比较

## 方案 A：大量 Fine-grained CRUD Tool

问题：

- Tool 数随数据库表增加；
- description 高重叠；
- LLM selection 变差；
- Policy 分散；
- mutation 语义不清；
- Audit 只剩“update row”；
- Context token 变大；
- Domain 结构变化污染 Agent Contract。

**不采用。**

## 方案 B：少量万能 Tool

例如：

```text
state.read
state.mutate
```

问题：

- Input Schema 巨大；
- 低风险/高风险动作混在一起；
- Policy / HITL 难确定；
- idempotency / transaction / audit 难表达；
- 模型自由度过高。

**不采用。**

## 方案 C：聚合 Read + 业务语义 Write

```text
少量聚合 Read
+
有限业务语义 Mutation
```

优点：

- Read 不让 Executive 拼数据库；
- Write 有稳定业务语义；
- Tool selection 清晰；
- Policy 可确定；
- transaction boundary 可解释；
- Result / Error 可统一；
- Tool 数不随表增长；
- Provider-neutral。

**V2.2 正式采用方案 C。**

---

# 8. Tool Granularity Rule

Tool 不按一个 SQL / 一个表 / 一个字段拆分。

是否拆 Tool，由以下维度决定：

```text
业务语义
Policy / HITL
风险与可逆性
Authorization
transaction boundary
idempotency / replay
required identity
input schema
business receipt
derived effects
```

如果这些维度明显不同，倾向拆开。

如果同一对象、同一业务语义、同一风险、同一权限、同一输入输出结构，可适度 consolidation。

---

# 9. Compound Tool 与多个 Tool 的边界

> **同一个不可拆 Domain invariant 可以由一个 Tool 形成多个 DB effects。**
>
> **同一句自然语言中仅仅同时出现的独立 effect，仍应获得独立 Tool Receipt。**

## 9.1 Task + Reminder

“下午三点提醒我取快递。”

```text
Task
+
Automation
```

允许一个 `task_create` 携带 `reminder`。

Application 根据输入进入：

```text
CreateTaskUseCase
或
CreateTaskWithReminderUseCase
```

后者在一个 PostgreSQL transaction 内形成 Task + linked Automation。

## 9.2 Thing + ThingDate

“我要参加软件杯，19号截止。”

推荐：

```text
thing_create
↓ receipt

thing_date_set
↓ receipt
```

允许真实 partial success。

## 9.3 Correction + Relative Automation recalculation

“截止改到20号。”

Executive 只调用：

```text
thing_date_set
```

Application 内部：

```text
ThingDate correction
+
StateMutation
+
relative Automation recalculation
```

后两项属于 derived effect。

---

# 10. Tool Registry

V2.2 使用：

> **Code-defined, version-controlled Tool Registry。**

不建设数据库 Tool Marketplace。

完整 Registry 与当轮可用 Tool Set 分离：

```text
Full Registry
↓
Eligibility Filter
↓
Allowed Tool Set for this Run/model call
↓
ModelGateway Provider Adapter
```

---

# 11. ToolDefinition 最小逻辑模型

```text
ToolDefinition

capability_id
model_tool_name

description

input_schema
output_schema

effect_kind

destructive
reversible
external_interaction
open_world

authorization_scope
allowed_run_scopes

execution_safety_class
replay_policy

requires_expected_version

application_binding

progress_key?
```

---

# 12. ToolDefinition 字段说明

## capability_id

Backend 内部稳定能力 ID：

```text
task.complete
state.get_overview
```

## model_tool_name

真正提供给模型的名字统一使用 Provider 公共字符集：

```text
task_complete
state_get_overview
thing_date_set
```

推荐 snake_case。

## description

只说明：

```text
what it does
when to use
when not to use
critical parameter semantics
important side effect
```

不塞 Policy Matrix、SQL、Credential、数据库结构。

## input_schema / output_schema

Registry 保存 canonical Tool Schema。

ModelGateway 转换到不同 Provider。

## effect_kind

建议：

```text
READ
MUTATION
EXTERNAL_EFFECT
```

## 行为 metadata

```text
destructive
reversible
external_interaction
open_world
```

这些是 Policy 输入，不是 Policy 决策。

## authorization_scope

保持简单：

```text
state:read
state:write
memory:read
memory:write
file:read
file:delete
web:read
automation:write
thing:delete
```

## allowed_run_scopes

```text
INTERACTIVE
AUTOMATION_CONDITION
AUTOMATION_REMINDER
SYSTEM_JOB
```

## execution_safety_class

```text
READ_ONLY
LOCAL_TRANSACTIONAL
EXTERNAL_IDEMPOTENT
EXTERNAL_RECONCILABLE
EXTERNAL_UNSAFE
```

## application_binding

绑定 Application Capability，不绑定 URL / ORM / SQL。

---

# 13. 不加入 ToolDefinition 的字段

V2.2 不保存：

```text
risk_score
importance
confidence
```

也不把：

```text
requires_confirmation = true
```

做成绝对 Tool property。

是否确认取决于：

```text
Tool metadata
+
Action
+
Run origin
+
resource state
+
Policy
```

---

# 14. Provider-neutral Schema 原则

Canonical Tool Schema 优先使用跨 Provider 稳定支持的 JSON Schema 公共子集：

```text
object
string
integer
number
boolean
array
small enum
required
simple nested object
```

谨慎使用复杂 `oneOf / anyOf / deep polymorphism / conditional schema`。

Strict Tool Use / Structured Outputs 只能保证 schema conformance，不能保证：

- ID 存在；
- resource 属于用户；
- expected_version 最新；
- 当前 Run 有权限；
- 用户语义确实指该对象。

---

# 15. Dynamic Tool Availability

```text
ToolRegistry
↓
Run Origin
↓
Execution Scope
↓
Authorization eligibility
↓
Provider capability
↓
Current task relevance
↓
Allowed Tool Set
```

完整 Registry ≠ 每次给模型的 Tool Set。

---

# 16. Run Origin

V2.2 最小：

```text
INTERACTIVE
AUTOMATION_CONDITION
AUTOMATION_REMINDER
SYSTEM_JOB
```

---

# 17. Interactive Run Tool Scope

Interactive Run 可获得较完整能力：

```text
State Read
State Write
Memory
File Read
Web
Automation
```

Restricted Tool MAY 获得 eligibility，但仍受 Policy / HITL。

---

# 18. Automation Condition Run Tool Scope

例如“官网公布结果以后告诉我”。

Automation 创建时固化 bounded Execution Scope：

```text
READ_STATE
WEB_SEARCH
URL_INSPECT
NOTIFY
```

后台 Run 默认不获得：

```text
Thing mutation
Task mutation
Date mutation
Memory mutation
Delete
Archive
```

超出 delegated scope：

```text
AUTHORIZATION_DENIED
```

不是 HITL 扩权。

---

# 19. Automation Reminder Run

普通 Reminder 通常只需要：

```text
读取相关 State
判断 Reminder 是否仍有意义
发送 Notification
```

不默认继承 Web / Memory / State Write。

---

# 20. Personal State Read Tool

正式采用：

```text
state_get_overview
state_get_thing_context
```

不为每表建设：

```text
thing_get
task_list
date_list
blocker_list
automation_list
```

---

# 21. state_get_overview

目的：

> **为了理解当前用户这句话，Executive 当前应该知道用户有哪些主要事项、近期行动与重要状态？**

SHOULD 返回：

```text
active Thing cards
near-term / relevant standalone Tasks
upcoming important ThingDates
open blocker summary
active Automation summary
recently changed important items
stable IDs
versions
truncation metadata
```

不返回：

- Long-term Memory；
- 全量 Timeline；
- 全量 StateMutation；
- 全部历史 Task；
- 全部 File 内容。

同时服务：

```text
current context
reference resolution
stable ID acquisition
expected_version acquisition
```

---

# 22. state_get_thing_context

输入：

```json
{
  "thing_id": "th_123"
}
```

Backend 自己执行 Context Budget。

SHOULD 返回：

```text
Thing identity/lifecycle/version
Current Soft State
active/recent Tasks + versions
ThingDates + versions
OPEN Blockers + versions
Automation summary + versions
lightweight File/Evidence refs
truncated flags
```

Long-term Memory 不混入 State Tool。

---

# 23. V2.2 不提供 thing_search / task_search

Thing candidate recall 保持 Runtime Context 能力：

```text
active_thing hint
+
small Thing Cards
+
candidate retrieval
+
Executive judgment
```

未来只有真实 Eval 证明必要才增加搜索 Tool。

---

# 24. Mutation Tool Input 原则

mutation input 尽量是：

> **stable ID + 真正要改变的业务参数 + expected_version。**

禁止让模型重述 Backend 已经知道的信息。

---

# 25. Stable ID First

mutation 不允许 name fallback。

目标不确定时：

```text
Executive
→ Read
→ resolve stable ID
→ mutation
```

不让 Application mutation 做自然语言 identity guessing。

---

# 26. LLM 不传 user_id / owner_id

以下来自 Runtime：

```text
user_id
owner_id
run_id
message_id
action_id
actor/channel provenance
```

不进入 model arguments。

Backend 用：

```text
AuthContext.internal_user_id
```

做 owner scope。

---

# 27. expected_version

已有 mutable entity 的重要 mutation MUST 携带：

```text
expected_version
```

来源必须是 authoritative Read Result。

冲突：

```text
VERSION_CONFLICT
→ Executive reread
→ semantic reassessment
```

ToolRuntime 不自动覆盖最新版本。

---

# 28. Time Input

自然语言时间由 Executive 理解，Tool 传结构化 TemporalValue：

```json
{
  "precision": "DATE_TIME",
  "local_value": "2026-09-18T15:00:00",
  "timezone": "Asia/Singapore"
}
```

或 DATE / MONTH 精度。

---

# 29. EvidenceRef

Tool input 如需 evidence，只接受 Backend 已返回的 stable EvidenceRef。

不允许模型自己填 arbitrary URL 作为 authoritative provenance。

---

# 30. 推荐 V2.2 Tool Set

完整 Registry 推荐 **21 个 capability**。

## STATE READ

```text
state_get_overview
state_get_thing_context
```

## STATE WRITE

```text
thing_create
thing_change_state
task_create
task_change_status
thing_date_set
thing_context_set
blocker_manage
```

## MEMORY

```text
memory_search
memory_remember
memory_forget
```

## FILE

```text
file_search
file_inspect
```

## WEB

```text
search_web
url_inspect
```

## AUTOMATION

```text
automation_create
automation_cancel
```

## RESTRICTED

```text
thing_merge
thing_delete
file_delete
```

---

# 31. thing_create

用途：创建新的持续现实事务。

不用于普通 Task / Reminder / Thread / 临时问答。

典型输入：

```json
{
  "title": "软件杯"
}
```

不得变成 `state.form_everything`。

---

# 32. thing_change_state

统一处理：

```text
COMPLETE
CANCEL
REACTIVATE
ARCHIVE
RESTORE
```

输入：

```json
{
  "thing_id": "th_123",
  "action": "ARCHIVE",
  "expected_version": 7
}
```

DELETE 不放进该 Tool。

---

# 33. task_create

创建 standalone / Thing-linked Task。

可携带：

```text
scheduled_time?
due_time?
recurrence?
reminder?
```

Reminder 存在时可进入 `CreateTaskWithReminderUseCase`。

---

# 34. task_change_status

统一处理：

```text
TODO
DONE
CANCELLED
```

示例：

```json
{
  "task_id": "ta_123",
  "target_status": "DONE",
  "expected_version": 4
}
```

不允许 arbitrary update 其他字段。

---

# 35. thing_date_set

统一处理：

```text
CREATE
CORRECT
```

对象限定：

```text
DEADLINE
EVENT
MILESTONE
```

CREATE 示例：

```json
{
  "operation": "CREATE",
  "thing_id": "th_123",
  "kind": "DEADLINE",
  "label": "作品提交截止",
  "value": {
    "precision": "DATE",
    "local_value": "2026-09-19"
  },
  "certainty": "CONFIRMED"
}
```

CORRECT 示例：

```json
{
  "operation": "CORRECT",
  "thing_date_id": "dt_123",
  "expected_version": 3,
  "value": {
    "precision": "DATE",
    "local_value": "2026-09-20"
  },
  "certainty": "CONFIRMED"
}
```

Relative Automation recalculation 是 derived effect。

---

# 36. thing_context_set

用于 Current Soft State：

```text
当前重点
当前策略
老师关注
当前情况
```

不是无限 append log。

---

# 37. blocker_manage

限定：

```text
OPEN
RESOLVE
```

OPEN：

```json
{
  "operation": "OPEN",
  "thing_id": "th_123",
  "summary": "等待老师提供实验数据"
}
```

RESOLVE：

```json
{
  "operation": "RESOLVE",
  "blocker_id": "bl_123",
  "expected_version": 2
}
```

---

# 38. memory_search

用于按需检索 Long-term Memory。

```json
{
  "query": "我之前比赛有没有因为提交问题出过错？",
  "types": ["EPISODIC"]
}
```

不把 vector threshold / hybrid weight 交给模型。

---

# 39. memory_remember

只有 Executive 已判断信息真正属于 Long-term Memory 时调用。

```json
{
  "content": "用户通常喜欢在晚上集中写代码",
  "type": "PROFILE"
}
```

执行：

```text
MemoryManager
→ CREATE / REVISE / CONSOLIDATE / IGNORE
```

不是 direct INSERT。

---

# 40. memory_forget

必须先 resolve stable Memory ID：

```json
{
  "memory_id": "mem_123",
  "expected_version": 4
}
```

范围模糊时先搜索 / 澄清。

---

# 41. file_search

从用户历史文件中发现相关文件和片段。

输入：

```json
{
  "query": "ADMM实验结果",
  "thing_id": "th_123"
}
```

输出 bounded candidates + matching fragments + stable file_id + locator。

---

# 42. file_inspect

针对已知 file_id 深入读取：

```json
{
  "file_id": "file_123",
  "question": "文档里最终截止日期是多少？"
}
```

Backend 决定实际 representation。

---

# 43. search_web

作用：发现外部公开信息。

典型：

```json
{
  "query": "2026 软件杯报名截止时间",
  "source_preference": "OFFICIAL_FIRST"
}
```

Search Result 是 external evidence，不自动修改 Personal State。

---

# 44. url_inspect

```text
search_web
= discovery

url_inspect
= exact known resource inspection
```

---

# 45. automation_create

支持：

```text
ONCE
RECURRING
RELATIVE
CONDITION
```

Scheduler 内部实现不在本专项展开。

---

# 46. automation_cancel

输入：

```json
{
  "automation_id": "au_123",
  "expected_version": 2
}
```

不额外提供 `automation_list`。

---

# 47. Restricted Tool

## thing_merge

涉及 canonical identity、reference rebinding、audit、redirect。

## thing_delete

不能塞进 `thing_change_state`，因为 destructive、wide impact、dependency preview、HITL。

## file_delete

删除原始文件与派生表示，必须独立 Tool。

---

# 48. 为什么没有 thread_delete

默认由 Product UI / HTTP API 主导。

未来 Eval 证明自然语言删 Thread 有真实收益再加。

---

# 49. Tool Result

Mutation Result 统一思想：

```json
{
  "status": "SUCCEEDED",
  "receipt": {
    "entity_type": "TASK",
    "entity_id": "ta_123",
    "operation": "SET_STATUS",
    "new_version": 5,
    "current_state": {
      "status": "DONE",
      "completed_at": "2026-08-28T08:20:00Z"
    },
    "derived_effects": []
  },
  "warnings": []
}
```

Executive 必须依据 persisted receipt 回答用户。

---

# 50. current_state projection

只返回此次回答真正有用的 current state。

不返回完整 ORM Entity。

---

# 51. derived_effects

只返回用户可感知 / Executive 需要知道的联动。

例如：

```json
{
  "type": "AUTOMATION_RESCHEDULED",
  "automation_id": "au_1",
  "summary": "相对提醒已同步调整到9月19日"
}
```

---

# 52. Read Tool Result

所有 Read Tool MUST：

```text
bounded
ranked
high-signal
ID-aware
version-aware
truncation-aware
```

禁止数据库 JSON dump。

---

# 53. Error Model

收敛为 11 类：

```text
INVALID_ARGUMENT
NOT_FOUND
VERSION_CONFLICT
AUTHORIZATION_DENIED
POLICY_DENIED
CONFIRMATION_REQUIRED
DOMAIN_CONFLICT
RATE_LIMITED
TEMPORARY_FAILURE
PERMANENT_FAILURE
UNKNOWN_OUTCOME
```

---

# 54. ToolError Envelope

```json
{
  "status": "ERROR",
  "error": {
    "code": "VERSION_CONFLICT",
    "message": "The task has changed since it was read.",
    "retryable": false,
    "resolution": "REREAD_STATE",
    "resource": {
      "type": "TASK",
      "id": "ta_123",
      "current_version": 5
    }
  }
}
```

不得返回 Stack Trace / ORM exception 给模型。

---

# 55. Error 默认处理

| Error | 默认处理 |
|---|---|
| INVALID_ARGUMENT | 修正参数；重复失败则停止 |
| NOT_FOUND | reread / reference resolution |
| VERSION_CONFLICT | reread State，禁止 blind retry |
| AUTHORIZATION_DENIED | 不绕过 |
| POLICY_DENIED | 不执行 |
| CONFIRMATION_REQUIRED | 进入 HITL |
| DOMAIN_CONFLICT | reread / clarify / resolve |
| RATE_LIMITED | MAY 按 Retry-After / budget 重试 |
| TEMPORARY_FAILURE | MAY，按 Safety Class |
| PERMANENT_FAILURE | 不自动重试 |
| UNKNOWN_OUTCOME | 禁止 blind retry，进入 reconciliation |

---

# 56. Authentication / Authorization / Policy / HITL

```text
Authentication
= 你是谁

Authorization
= 当前身份 / Run 有没有资格调用这个能力

Policy
= 这次具体 Action 是否允许直接执行

HITL
= Policy 判定必须重新取得用户授权时的交互
```

---

# 57. Ambiguity 边界

开放式语义 Ambiguity 主要由 Executive 解决。

例如“把那个项目删了”有两个候选，应先 Read → resolve / clarify，不让 Policy 再调第二个 LLM。

---

# 58. 不实现风险数值公式

不实现：

```text
risk = Ambiguity × Impact × Reversibility × Authorization
```

而实现 staged pipeline：

```text
Semantic Resolution
↓
Authentication
↓
Authorization
↓
Deterministic Policy
↓
ALLOW / DENY / REQUIRE_CONFIRMATION
↓
HITL if required
↓
revalidation
↓
execution
```

---

# 59. Authorization 输入

最小：

```text
AuthContext
RunContext
ToolDefinition
resolved target resource
resource ownership
Automation execution scope?
```

不建设企业级 RBAC。

---

# 60. Authorization 核心规则

```text
authenticated internal user?
target owned by current user?
current Run origin allowed?
current Automation execution scope allows capability?
```

Tool 本身安全 ≠ 当前 Run 有资格执行。

---

# 61. Automation Run 超权

Condition Automation 若尝试：

```text
thing_date_set
thing_delete
memory_forget
```

返回：

```text
AUTHORIZATION_DENIED
```

不进入 HITL。

---

# 62. ToolPolicyService

输入：

```text
ToolDefinition
RuntimeToolAction
AuthContext
RunContext
latest relevant State
```

输出：

```text
ALLOW
DENY
REQUIRE_CONFIRMATION
```

附：

```text
reason_code
public_rationale?
confirmation_spec?
```

Policy MUST deterministic。

---

# 63. Policy 不使用 LOW / MEDIUM / HIGH 总分

Registry 保存真实行为事实，不保存不可解释 risk score。

---

# 64. Policy Behavior Class

可使用：

```text
READ_ONLY
OPEN_WORLD_READ
ROUTINE_REVERSIBLE_MUTATION
LONG_LIVED_EFFECT
DESTRUCTIVE_MUTATION
EXTERNAL_WRITE
```

这是行为类别，不是总分。

---

# 65. HITL 原则

HITL 只回答：

> **用户是否明确授权这一项已经解析清楚、影响明确的副作用？**

不作为第二语义理解器，不对所有 Write 确认，不给 Automation Run 扩权。

---

# 66. 默认无需 HITL

通常直接执行并回执：

```text
普通 Task 创建
Task 完成 / 取消 / reopen
Thing create
Thing complete / cancel / reactivate
Thing archive / restore
Deadline create / explicit correction
Current Soft State 更新
Blocker open / resolve
Memory remember
精确 Memory forget
普通 Reminder
Recurring Reminder
Condition Watch
Automation cancel
Web Search
URL Inspect
File Search / Inspect
```

前提是目标明确、Authorization 通过、Domain invariant 正常。

---

# 67. 默认必须 HITL

V2.2：

```text
thing_merge
thing_delete
file_delete
```

未来真实 External Write 默认也需要明确授权，除非用户已通过具体 Automation Definition 预先授权到明确范围。

---

# 68. Deadline correction 的冲突例外

用户明确纠错通常直接执行。

但如果：

```text
Current State:
19号 CONFIRMED

新 Web Evidence:
20号
```

而用户只让“查官网”，应进入：

```text
DOMAIN_CONFLICT
```

由 Executive 解释冲突，不能自动覆盖 Current State。

---

# 69. Memory Forget

精确 resolve 的 Memory：

```text
memory_forget
→ ALLOW
```

范围模糊时先搜索 / 澄清。

---

# 70. Automation 创建

用户明确提出 Reminder / Recurring / Condition Watch 时，满足系统边界即可 ALLOW。

Agent 只是主动建议时，不能未经用户同意创建。

---

# 71. Open-world Read

`search_web / url_inspect` 默认可执行，但输出属于不可信外部信息：

```text
≠ Personal State
≠ authorization instruction
```

网页内容不能命令 Agent 执行本地副作用。

---

# 72. Tool Policy Matrix

| Tool / Action | Interactive | Automation Run | HITL |
|---|---|---|---|
| state_get_overview | ALLOW | scope 内 ALLOW | 否 |
| state_get_thing_context | ALLOW | scope 内 ALLOW | 否 |
| thing_create | ALLOW | DENY | 否 |
| thing_change_state COMPLETE | ALLOW | DENY | 否 |
| thing_change_state CANCEL | ALLOW | DENY | 否 |
| thing_change_state REACTIVATE | ALLOW | DENY | 否 |
| thing_change_state ARCHIVE | ALLOW | DENY | 否 |
| thing_change_state RESTORE | ALLOW | DENY | 否 |
| task_create | ALLOW | DENY | 否 |
| task_change_status | ALLOW | DENY | 否 |
| thing_date_set CREATE | ALLOW | DENY | 通常否 |
| thing_date_set CORRECT | ALLOW | DENY | 事实冲突时 MAY |
| thing_context_set | ALLOW | DENY | 否 |
| blocker_manage | ALLOW | DENY | 否 |
| memory_search | ALLOW | 默认 DENY | 否 |
| memory_remember | ALLOW | DENY | 否 |
| memory_forget | ALLOW | DENY | 精确目标时否 |
| file_search | ALLOW | 默认 DENY | 否 |
| file_inspect | ALLOW | delegated file scope MAY | 否 |
| search_web | ALLOW | delegated web scope MAY | 否 |
| url_inspect | ALLOW | delegated web scope MAY | 否 |
| automation_create | ALLOW | DENY | 用户明确请求时否 |
| automation_cancel | ALLOW | DENY | 否 |
| thing_merge | Authorized | DENY | 必须 |
| thing_delete | Authorized | DENY | 必须 |
| file_delete | Authorized | DENY | 必须 |

---

# 73. Approval 语义

HITL Approval 必须绑定：

```text
run_id
action_id
capability_id
arguments_hash
target IDs
material consequence snapshot
```

Approval 不是永久授权。

---

# 74. Approval 后重新校验

用户 APPROVE 后必须重新：

```text
Authentication
Authorization
Policy
resource ownership
latest State
expected_version
Domain invariant
```

State 已变化则 `VERSION_CONFLICT`，必要时重新确认。

---

# 75. ConfirmationSpec

由 Backend 确定性生成：

```text
title
public explanation
target display name
important consequences
irreversible/destructive warning
```

依赖后果不得由 LLM自由编造。

---

# 76. PolicyDecision persistence

V2.2 不建独立 `policy_decisions` 表。

Policy outcome / reason code 只记录在 execution / HITL / audit 所需位置。

---

# 77. RuntimeToolAction

```text
RuntimeToolAction

action_id
run_id
capability_id
model_tool_name
canonical arguments
arguments_hash
provider_call_id?
```

`provider_call_id` 仅 correlation metadata。

---

# 78. action_id

`action_id` 是一次 Agent Tool 业务动作的 durable identity。

Provider tool_call_id 不是业务执行主键。

---

# 79. action_id 生成时机

```text
Model returns Tool Call
↓
assign action_id
↓
resolve ToolDefinition
↓
schema validation
↓
canonicalize args
↓
arguments_hash
↓
durable checkpoint RuntimeToolAction
↓
Authorization / Policy / HITL / execution
```

任何副作用前，action identity 必须 durable。

---

# 80. arguments_hash

同一 action_id MUST 永远绑定同一 canonical arguments hash。

same action_id + different hash = Runtime invariant violation。

---

# 81. ToolExecution Ledger

```text
ToolExecution

action_id UNIQUE
run_id
capability_id
arguments_hash

status
attempt_count

lease_owner?
lease_expires_at?
lease_token?

receipt?
error_code?

provider_idempotency_key?
provider_request_id?

started_at
finished_at?
```

不是 Chain-of-Thought。

---

# 82. ToolExecution 状态

```text
IN_PROGRESS
SUCCEEDED
FAILED
UNKNOWN_OUTCOME
```

不增加 PENDING / CANCELLED。

---

# 83. 为什么没有 PENDING

未开始由 RuntimeToolAction + checkpoint 表达。

等待用户由 HITL Interaction 表达。

---

# 84. 为什么没有 CANCELLED

Run Cancel 不等于已开始副作用被撤销。

已开始 Tool 最终必须收敛为 SUCCEEDED / FAILED / UNKNOWN_OUTCOME。

---

# 85. 状态转换

```text
             IN_PROGRESS
             /    |     \
            /     |      \
     SUCCEEDED  FAILED  UNKNOWN_OUTCOME
                          /        \
                         /          \
                    SUCCEEDED      FAILED
```

---

# 86. Read Tool 也进入 Ledger

same action crash 后可 replay persisted result。

Read 尚未持久化结果就 crash 时，READ_ONLY 可以安全重试。

新用户问题产生 new action_id。

---

# 87. 内部 PostgreSQL Mutation

对 LOCAL_TRANSACTIONAL Tool：

> **业务 mutation、业务 audit 与 Tool SUCCEEDED Receipt 尽量在同一个 PostgreSQL transaction 中完成。**

```text
BEGIN

validate execution ownership / lease token

UPDATE domain entity
WHERE version = expected_version

INSERT state_mutation ...

UPDATE tool_execution
SET status = SUCCEEDED, receipt = ...
WHERE action_id = ...
AND lease_token = ...

COMMIT
```

---

# 88. 同事务的意义

避免：

```text
业务已经 COMMIT
↓
Worker crash
↓
Ledger 不知道成功
```

内部 PostgreSQL mutation 应尽量做到：

```text
业务成功
⇔
Ledger SUCCEEDED + receipt 成功
```

---

# 89. Tool Claim

执行前：

```text
create / claim ToolExecution
status = IN_PROGRESS
lease_owner
lease_expires_at
lease_token
COMMIT
```

不要把外部 HTTP 调用包含在长 DB transaction。

---

# 90. Multi-worker Claim

`action_id` MUST UNIQUE。

逻辑：

```text
if no ToolExecution:
    create IN_PROGRESS + lease

elif SUCCEEDED:
    replay receipt

elif FAILED:
    replay persisted error

elif IN_PROGRESS and lease active:
    do not execute

elif IN_PROGRESS and lease expired:
    recover according execution class

elif UNKNOWN_OUTCOME:
    reconcile
```

---

# 91. Lease

lease 只表达当前哪个 Worker 负责 execution。

它不是 action identity，也不是 idempotency key。

---

# 92. Fencing / lease_token

claim 时产生 `lease_token / claim_epoch`。

finalize 必须带当前 token。

旧 Worker affected rows = 0 时停止提交结果。

---

# 93. SKIP LOCKED 边界

`FOR UPDATE SKIP LOCKED` MAY 用于 Run queue / Durable Job queue / Worker claim。

不得作为业务状态一致性或 idempotency identity 机制。

---

# 94. Advisory Lock

V2.2 ToolRuntime 不默认使用 advisory lock。

UNIQUE action_id + row state + lease + fencing 已足够。

---

# 95. Execution Safety Class

```text
READ_ONLY
LOCAL_TRANSACTIONAL
EXTERNAL_IDEMPOTENT
EXTERNAL_RECONCILABLE
EXTERNAL_UNSAFE
```

---

# 96. READ_ONLY

例如 State Read / Memory Search / File Search / Web Search。

未持久化结果前 crash 通常可安全重试。

---

# 97. LOCAL_TRANSACTIONAL

Thing / Task / Date / Blocker / Memory / Automation local mutation。

依赖 PostgreSQL transaction + expected_version + action_id + receipt。

---

# 98. EXTERNAL_IDEMPOTENT

Provider 支持 idempotency key。

恢复时 MAY retry same key。

---

# 99. EXTERNAL_RECONCILABLE

Provider 无安全 retry，但可以通过 client reference / provider request ID / status query 确认状态。

timeout 后先 reconcile。

---

# 100. EXTERNAL_UNSAFE

无 idempotency、无 status query、无 reliable correlation。

timeout：

```text
UNKNOWN_OUTCOME
```

禁止自动再次执行。

---

# 101. Runtime replay idempotency

Agent Runtime replay key：

```text
action_id
```

同一 action：

```text
same action_id
same args hash
same persisted result
```

---

# 102. Runtime retry 与新决策分离

技术重试：

```text
same action_id
attempt_count++
```

Executive reread 后重新决定：

```text
new action_id
```

---

# 103. Runtime idempotency ≠ semantic dedupe

用户两次独立说“完成它”，是两个 user intents。

第二次 new action_id。

Application MAY 返回 already DONE / no-op receipt。

---

# 104. HarmonyOS HTTP request idempotency

区分：

```text
Agent Runtime replay
→ action_id

HarmonyOS retry-sensitive POST
→ request idempotency key

External provider retry
→ provider idempotency key
```

---

# 105. 哪些 HTTP Command 更需要 Idempotency-Key

尤其：

```text
Create Thing
Create Task
Create Automation
Create Task + Reminder
```

因为网络重试容易形成 duplicate entity。

---

# 106. HTTP Idempotency Record

如需持久化，仅建设极薄：

```text
RequestIdempotencyRecord

user_id
operation
idempotency_key
request_hash
receipt
```

不把 HarmonyOS 请求塞进 ToolExecution。

---

# 107. External Provider Idempotency Key

```text
derive / allocate key
↓
persist BEFORE external request
↓
all retries reuse same key
```

---

# 108. External Timeout

外部 mutating request timeout：

```text
timeout
≠ definite failure
```

必须按 Execution Safety Class 收敛。

---

# 109. External Idempotent Timeout

```text
timeout
↓
same provider idempotency key
↓
bounded retry
```

---

# 110. External Reconcilable Timeout

```text
timeout
↓
DO NOT retry mutation
↓
query remote state
↓
found succeeded → SUCCEEDED
found definitely absent → MAY retry
cannot determine → UNKNOWN_OUTCOME
```

---

# 111. External Unsafe Timeout

```text
UNKNOWN_OUTCOME
↓
NO BLIND RETRY
```

向用户诚实说明无法确认结果。

---

# 112. Generic Retry 禁止

Retry 决策必须结合：

```text
Execution Safety Class
failure phase
provider idempotency
reconciliation ability
retry budget
```

---

# 113. Runtime 自动 Retry Matrix

| Error | Runtime Auto Retry |
|---|---|
| INVALID_ARGUMENT | 否 |
| NOT_FOUND | 否 |
| VERSION_CONFLICT | 否 |
| AUTHORIZATION_DENIED | 否 |
| POLICY_DENIED | 否 |
| CONFIRMATION_REQUIRED | HITL |
| DOMAIN_CONFLICT | 否 |
| RATE_LIMITED | MAY |
| TEMPORARY_FAILURE | MAY，按 Safety Class |
| PERMANENT_FAILURE | 否 |
| UNKNOWN_OUTCOME | 禁止 blind retry |

---

# 114. PostgreSQL connection failure around COMMIT

连接在 COMMIT 附近断开时，不能凭异常判断事务一定失败。

恢复后：

```text
reconnect
↓
query ToolExecution by action_id
```

SUCCEEDED 则 replay receipt。

---

# 115. PostgreSQL unavailable

对于依赖 durable guarantee 的 mutation / external Tool：

> **不得开始现实副作用。**

因为 action identity / ledger / idempotency key / receipt 无法可靠持久化。

---

# 116. Redis outage

Redis 故障不得丢失：

```text
Run
ToolExecution
Personal State
Memory
Automation
durable Job
```

Worker / Recovery 使用 PostgreSQL fallback polling。

---

# 117. Tool Result Size

Agent-visible Tool Result MUST bounded。

大内容使用 durable Evidence / File / Search Resource + stable ref。

---

# 118. Tool Result Replay

same action_id：

```text
SUCCEEDED
→ replay same persisted bounded result/ref
```

不是重新执行 Tool。

---

# 119. Client-visible Tool Progress

保持：

```text
tool.started
tool.completed
tool.failed
```

不设计虚假百分比进度。

---

# 120. Progress Metadata

ToolDefinition MAY 有 `progress_key`，由 HarmonyOS Presentation 层映射真实文案。

不让 LLM 编造执行进度。

---

# 121. 很快的本地 Mutation

Runtime仍可产生真实 started/completed event。

UI MAY 对极短执行不展示 loading，属于 Presentation Policy。

---

# 122. UNKNOWN_OUTCOME UI

通过 `tool.failed`，但：

```text
code = UNKNOWN_OUTCOME
public_message = 结果暂时无法确认
```

UI 不应误导为肯定失败。

---

# 123. HTTP Product API 总体能力边界

HarmonyOS V2.2 需要能力级 HTTP Surface：

```text
Authentication / Session

Thread / Message / Run

SSE Run Events / Replay

Personal State Overview
Thing Detail

Task UI actions
Thing UI actions

File Upload / Metadata / Delete

Automation View / Create / Cancel

Today / Home derived reads

HITL Pending Action / Approve / Reject

Account / Device / Push
```

不把 ToolExecution / PolicyDecision / StateMutation / MemoryManager 暴露成普通 Product CRUD API。

---

# 124. UI 与 Agent 共用 Application

HarmonyOS：

```text
POST /tasks/{id}/complete
→ CompleteTaskUseCase
```

Agent：

```text
task_change_status
→ ToolRuntime
→ CompleteTaskUseCase
```

共享 Domain invariant / version / transaction / receipt / StateMutation。

不共享 wire Contract。

---

# 125. UI Confirmation 与 Agent HITL

UI 可自行在高影响 Delete 前弹 Product confirmation。

Agent 则：

```text
file_delete
→ Policy REQUIRE_CONFIRMATION
→ HITL
→ same DeleteFileUseCase
```

共享 Application 风险语义，不共享交互方式。

---

# 126. HTTP Error

Application Error 可映射为：

```text
ToolError
或
HTTP Problem Details
```

HTTP MAY 使用 RFC 9457 `application/problem+json`。

---

# 127. HTTP expected_version

Product API mutation 也必须提供客户端读取到的 current version。

最终 MAY 使用：

```text
request body expected_version
```

或：

```text
ETag / If-Match
```

实施专项再冻结。

---

# 128. MutationReceipt

MutationReceipt 是 Contract concept，不单独建表。

Agent receipt 持久化于 ToolExecution.receipt。

业务历史由 StateMutation / TimelineEvent 负责。

---

# 129. ToolDefinition persistence

ToolDefinition code-defined / version-controlled。

不落 ToolDefinition 业务表。

---

# 130. PolicyDecision persistence

V2.2 不建独立 PolicyDecision 表。

只保存 execution / HITL / audit 真正必要的 outcome / reason metadata。

---

# 131. 真正必须 Durable 的 Tool 相关对象

至少：

```text
RuntimeToolAction
ToolExecution
HITL Interaction
Application business entities
StateMutation
Run / checkpoint
```

可选：

```text
HTTP RequestIdempotencyRecord
```

---

# 132. User Journey 1 — “Demo 做完了。”

```text
Executive
↓
state_get_thing_context
↓
Task ta1 TODO v4
↓
RuntimeToolAction A1
task_change_status(DONE, expected_version=4)
↓
Authorization PASS
↓
Policy ALLOW
↓
ToolExecution IN_PROGRESS
↓
PostgreSQL transaction

Task v4 → DONE v5
StateMutation
ToolExecution → SUCCEEDED + Receipt

COMMIT
↓
Executive receives persisted receipt
↓
“Demo 已标记完成。”
```

---

# 133. User Journey 2 — “不是19号，是20号。”

```text
state_get_thing_context
↓
ThingDate d1 = 19号 v3
↓
thing_date_set(CORRECT, expected_version=3)
↓
ALLOW
↓
Application
```

内部：

```text
ThingDate → 20
StateMutation
Relative Automation recalculation
ToolExecution receipt
```

---

# 134. User Journey 3 — “记住我喜欢晚上写代码。”

```text
semantic type = PROFILE Memory
↓
memory_remember
↓
MemoryManager
↓
CREATE / REVISE / CONSOLIDATE / IGNORE
↓
persisted receipt
```

只有成功后才说“记住了”。

---

# 135. User Journey 4 — “记住，截止日期改到20号。”

正确：

```text
thing_date_set
```

错误：

```text
memory_remember
```

---

# 136. User Journey 5 — “帮我查官网看看结果出来没。”

```text
search_web
↓
bounded Search Result
↓
Executive
```

只是回答时不形成 State。

只有当前现实确实需要修改时，再调用 State mutation。

---

# 137. User Journey 6 — “18号提醒我提交。”

如果已有 Task：

```text
automation_create
```

关联已有 Task。

如果没有 Task 且语义明显是用户未来行动：

```text
task_create(
  title = 提交材料,
  reminder = 18号
)
```

Application 原子创建 Task + Automation。

---

# 138. User Journey 7 — “把那个项目删了。”

若 target ambiguous：

```text
Executive clarify
```

resolve 后：

```text
thing_delete
↓
Authorization PASS
↓
Policy REQUIRE_CONFIRMATION
↓
deterministic dependency preview
↓
HITL
↓
APPROVE
↓
revalidate latest State / expected_version
↓
DeleteThingUseCase
```

---

# 139. User Journey 8 — UI 与 Agent 同时改 Task

Agent读 TODO v4，UI 先改 DONE v5。

Agent mutation expected_version=4：

```text
VERSION_CONFLICT
```

Executive reread 后发现 already DONE，不再写。

---

# 140. User Journey 9 — Tool 成功后 Worker crash

业务 mutation + StateMutation + ToolExecution SUCCEEDED + Receipt 同 PostgreSQL transaction COMMIT。

随后 crash。

恢复：

```text
same action_id
↓
Ledger SUCCEEDED
↓
replay persisted receipt
```

不重复副作用。

---

# 141. User Journey 10 — External timeout

未来 external write：

- Provider 支持 idempotency → retry same key；
- 可查询 → reconcile first；
- neither → UNKNOWN_OUTCOME，不 blind retry。

---

# 142. Failure Matrix

| Failure | 收敛 |
|---|---|
| Model hallucinated invalid ID | NOT_FOUND → reread |
| Tool args schema invalid | execution 前拒绝 |
| Tool exists but Run unauthorized | AUTHORIZATION_DENIED |
| expected_version stale | VERSION_CONFLICT → reread |
| Application invariant rejected | DOMAIN_CONFLICT |
| Ledger SUCCEEDED but Graph 未拿到 result | replay persisted receipt |
| 两 Worker 同时看到 same action | UNIQUE action + lease/fencing |
| HITL approval 后 State 已改变 | revalidate → conflict / new confirmation |
| Redis down | PostgreSQL truth + fallback polling |
| PostgreSQL unavailable before mutation | 不开始 side effect |
| PostgreSQL connection lost around COMMIT | reconnect → query action_id Ledger |
| external read timeout | bounded safe retry |
| external write timeout + provider key | retry same key |
| external write timeout + queryable | reconcile |
| external write timeout + neither | UNKNOWN_OUTCOME |
| Tool Result 太大 | bounded projection + stable ref |
| Tool description 重叠 | Tool Eval + active set 收敛 |
| old Worker lease 失效后恢复 | fencing token 阻止 stale finalize |
| same action_id with different args | Runtime invariant failure |

---

# 143. Tool Description Reliability

Tool description SHOULD 明确：

```text
what
when
when not
identity requirements
important side effects
key parameter semantics
```

不要写服务端秘密。

用 Tool Eval、description refinement、active Tool Set reduction 解决 selection 问题，不增加第二 LLM 检查器。

---

# 144. Client Progress Integrity

客户端状态只来自真实 Runtime Event。

禁止 LLM 在 Tool 未持久化成功前声称“已经完成”。

---

# 145. 官方设计依据

本文使用以下官方/标准资料校准设计原则，老实人不机械照搬其内部架构。

## LangGraph

Interrupts：

https://docs.langchain.com/oss/python/langgraph/interrupts

官方说明 interrupt resume 会重新执行节点，因此 side effects 必须幂等。

## OpenAI

Model guidance / allowed tools：

https://developers.openai.com/api/docs/guides/latest-model

其 `allowed_tools` 支持完整 Toolkit 与当前允许子集分离。

## Anthropic

How tool use works：

https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works

Define tools：

https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools

Strict tool use：

https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use

其官方强调 Tool 是模型与应用之间的 Contract，模型只产生结构化请求，应用负责实际执行。

## Google Gemini

Function calling：

https://ai.google.dev/gemini-api/docs/function-calling

官方支持 allowed tools / allowed function names 和 validated function calling。

## MCP

Tool schema / annotations：

https://modelcontextprotocol.io/specification/2025-11-25/schema

`readOnlyHint / destructiveHint / idempotentHint / openWorldHint` 都只是 hint，不是安全授权保证。

## PostgreSQL

Transaction Isolation：

https://www.postgresql.org/docs/current/transaction-iso.html

Explicit Locking：

https://www.postgresql.org/docs/current/explicit-locking.html

SELECT / SKIP LOCKED：

https://www.postgresql.org/docs/current/sql-select.html

本文据此采用：

```text
Read Committed + expected_version
short transaction
queue-like claim MAY SKIP LOCKED
no long transaction waiting LLM/HITL
```

## Stripe Idempotency

https://docs.stripe.com/api/idempotent_requests

借鉴“同一操作 key + 同一参数 + 重放持久化结果”的成熟设计思想。

## HTTP Standards

RFC 9110：

https://www.rfc-editor.org/rfc/rfc9110.html

RFC 9457：

https://www.rfc-editor.org/rfc/rfc9457.html

---

# 146. 最终 Tool Set 汇总

```text
CORE STATE READ
1. state_get_overview
2. state_get_thing_context

STATE WRITE
3. thing_create
4. thing_change_state
5. task_create
6. task_change_status
7. thing_date_set
8. thing_context_set
9. blocker_manage

MEMORY
10. memory_search
11. memory_remember
12. memory_forget

FILE
13. file_search
14. file_inspect

WEB
15. search_web
16. url_inspect

AUTOMATION
17. automation_create
18. automation_cancel

RESTRICTED
19. thing_merge
20. thing_delete
21. file_delete
```

完整 Registry 21 个 capability。

一次 Model Call 的 Allowed Tool Set SHOULD 根据 Run / Task 收窄，不要求一次性暴露 21 个。

---

# 147. Frozen Decisions

以下在 Tool/API/Policy v2.2 进入 Backend Freeze 后不得随意修改。

1. Application Use Case、HTTP Product API、Agent Tool 是三层不同 Contract。
2. HTTP 与 Tool 是同级 Adapter，复用 Application，不互相包装。
3. Tool 不直接访问 ORM / Repository / SQL。
4. Application Surface 大于 Agent Tool Surface。
5. Tool Architecture 使用“聚合 Read + 业务语义 Write”。
6. Tool Granularity 按业务语义、Policy、事务、幂等、输入输出决定，不按数据库表。
7. Derived effect 不额外暴露 Agent Tool。
8. 同一不可拆业务 invariant 可由一个 semantic Tool 形成多个 DB effect。
9. 独立 durable effect 保留独立 Tool Receipt。
10. Tool Registry code-defined / version-controlled。
11. 完整 Registry 与 Run-scoped Allowed Tool Set 分离。
12. Internal capability ID 与 model-facing snake_case name 分离。
13. Canonical Tool Schema Provider-neutral。
14. Schema 使用跨 Provider 稳定公共子集。
15. State Read 正式使用 `state_get_overview / state_get_thing_context`。
16. State Read 不混入 Long-term Memory。
17. V2.2 暂不提供 `thing_search / task_search`。
18. Mutation 使用 stable ID，禁止 name fallback。
19. model arguments 不携带 user_id / owner_id / actor / run_id 等 Runtime 已知信息。
20. 重要 mutable entity mutation 使用 expected_version。
21. 时间通过结构化 TemporalValue 进入 Tool。
22. Evidence 只接受 stable EvidenceRef。
23. 推荐完整 Registry 为 21 个 capability。
24. Read Result bounded/high-signal/version-aware。
25. Mutation Result 必须包含 persisted business receipt。
26. Error Model 冻结为 11 类。
27. Authentication、Authorization、Policy、HITL 四层分离。
28. 开放式语义 Ambiguity 由 Executive 处理。
29. Policy deterministic，不调用第二个 LLM。
30. 不实现风险数值总分。
31. Automation Run 只使用创建时 delegated Execution Scope。
32. Automation Run 超权直接 DENY，不通过 HITL 扩权。
33. Routine reversible mutation 默认自动执行。
34. `thing_merge / thing_delete / file_delete` 默认必须 HITL。
35. 精确 Memory Forget 默认不额外 HITL。
36. 用户明确请求的 Reminder / Condition Watch 默认可自动创建。
37. Open-world read 默认允许，但结果不获得 State authority。
38. Approval 绑定 action_id + arguments_hash + targets + material consequences。
39. Approval 后执行前必须重新校验最新 State / version / Policy / Authorization。
40. Confirmation consequences 由 Backend 确定性生成。
41. PolicyDecision 不单独建设 Domain table。
42. action_id 是 Agent Tool durable identity。
43. Provider tool_call_id 只作 correlation metadata。
44. action_id + canonical args hash 必须在副作用前 durable。
45. 同 action_id 不允许不同 args hash。
46. ToolExecution Ledger 状态仅 `IN_PROGRESS / SUCCEEDED / FAILED / UNKNOWN_OUTCOME`。
47. Read Tool 也可以使用 Ledger 重放 persisted result。
48. 内部 PostgreSQL mutation 应使业务 mutation + audit + Ledger SUCCEEDED receipt 同事务完成。
49. action claim 使用 unique action + lease + fencing。
50. lease 不是 idempotency identity。
51. `SKIP LOCKED` 只用于 queue-like claim。
52. ToolRuntime 不默认引入 advisory lock。
53. Execution Safety Class 冻结为 5 类。
54. Technical retry 保持同 action_id；Executive 新决策使用新 action_id。
55. Runtime idempotency ≠ semantic dedupe。
56. Agent action_id、HTTP idempotency key、External provider idempotency key 三层分离。
57. External mutating timeout 不允许 generic blind retry。
58. External unsafe timeout 正式使用 UNKNOWN_OUTCOME。
59. Tool Result 必须 bounded，大结果使用 stable resource ref。
60. Client progress 来自真实 Runtime Event，不由 LLM 编造。
61. HTTP Product API 与 Tool 共享 Application Error 语义，但 wire Contract 独立。
62. MutationReceipt 是 Contract concept，不单独建表。
63. ToolDefinition 不进数据库 Tool Registry 表。
64. PostgreSQL 不可用时不得开始依赖 durable execution guarantee 的副作用。

---

# 148. Deferred Details

## Tool Contract

- 每个 Tool 的最终 JSON Schema；
- 最终 Description 文案；
- Tool input examples；
- Provider strict mode 配置；
- 每轮 Allowed Tool selector 实现。

## Application

- Application class / module 命名；
- Command object；
- Repository method；
- final transaction code；
- exact derived effect orchestration。

## Database

- ToolExecution 最终表名；
- 列类型；
- index；
- lease duration；
- heartbeat interval；
- claim SQL；
- receipt JSONB schema；
- HTTP Idempotency table 是否首版启用。

## Policy

- reason_code 最终 enum；
- Delete dependency preview DTO；
- ConfirmationSpec 最终 contract；
- future External Write Policy。

## HTTP

- 最终 REST path；
- ETag / If-Match vs body expected_version；
- Idempotency-Key 应用于哪些 endpoint；
- RFC 9457 problem type URIs；
- Pagination contract；
- OpenAPI JSON。

## File/Search

- Search provider；
- exact URL retrieval internals；
- File parser；
- Evidence persistence；
- Search Result persistence；
- chunk / retrieval architecture。

## Automation

- Scheduler data model；
- occurrence；
- Condition execution details；
- Notification delivery；
- Automation execution scope representation。

---

# 149. Backend Freeze 验收问题

本专项冻结后，开发人员必须能明确回答：

1. Executive 到底有哪些 Tool？  
   → 第 146 节 21 个完整 Registry capability；单次 Run 动态收窄。

2. 为什么不是数据库 CRUD？  
   → Tool 表达业务能力，数据库结构由 Application / Domain 隔离。

3. HTTP API 和 Agent Tool 为什么不是一回事？  
   → 调用方、Contract 优化目标、确认交互、wire format 不同，但复用 Application。

4. Tool 如何调用 Application？  
   → ToolDefinition application binding / Tool Adapter，禁止直连 ORM。

5. 哪些 Tool 可以自动执行？  
   → Routine reversible mutation、Read、明确 Reminder / Watch 等。

6. 哪些必须 HITL？  
   → 至少 Thing Merge/Delete、File Delete。

7. Automation Run 为什么不能拥有所有 Tool？  
   → 只继承创建时 delegated Execution Scope。

8. Tool 重试为什么不会重复现实副作用？  
   → action_id + args hash + Ledger + local transaction / provider idempotency / reconciliation。

9. UI 和 Agent 同时修改怎么办？  
   → expected_version → VERSION_CONFLICT → reread → reassess。

10. 外部操作结果不确定怎么办？  
   → same provider key / reconcile / UNKNOWN_OUTCOME，绝不 blind retry。

11. 一个 Tool 成功以后 Agent 为什么可以可信地告诉用户“已经完成”？  
   → Application 成功 + durable ToolExecution SUCCEEDED receipt。

12. Model Provider 换掉以后为什么 Tool Contract 仍稳定？  
   → Registry 和 canonical schema Provider-neutral；Adapter 负责 Provider protocol。

13. Tool 数量为什么不会随数据库表增长？  
   → Tool 由业务能力决定，不由数据表决定。

14. 新能力什么时候值得新增 Tool？  
   → 只有 Executive 需要独立选择，且现有 Tool 无法在不破坏语义/Policy/事务边界的情况下表达。

15. Backend Freeze 后哪些 Contract 不能轻易改？  
   → capability semantic、三层边界、receipt/error、expected_version、action_id/replay、Policy/HITL、Automation scope、Ledger semantics。

---

# 150. 一句话定义

> **老实人 Tool / API / Policy v2.2 是一套以 Application Use Case 为唯一业务能力核心、以少量聚合 Read 和业务语义 Write 暴露给 Single Executive、以 Run-scoped Tool Registry、稳定 ID、expected_version、deterministic Authorization/Policy/HITL、PostgreSQL ToolExecution Ledger、action_id 幂等重放和 External UNKNOWN_OUTCOME 保护现实副作用，并通过独立 HarmonyOS HTTP Product API 复用同一 Domain 能力的 Provider-neutral Agent 执行契约。**
