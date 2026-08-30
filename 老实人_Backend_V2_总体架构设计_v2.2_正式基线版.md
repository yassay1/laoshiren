# 老实人 Backend V2 总体架构设计

> **版本**：v2.2  
> **状态**：正式架构基线（Approved for Detailed Design & Implementation）  
> **适用阶段**：Backend V2 — Backend Complete  
> **下一阶段**：V3 — HarmonyOS Client & Product Experience  
> **更新时间**：2026-08-28  
> **性质**：Backend V2 上位约束与开发“宪法”

---

## 0. 文档定位

本文定义 Backend V2 的**核心领域边界、总体技术路线、运行时原则、可靠性要求与冻结标准**。

```text
项目定位 / PRD
        ↓
Backend V2 总体架构设计（本文）
        ↓
专项技术设计
        ↓
Contract / Migration / 开发实施路线
        ↓
代码与测试
```

专项设计和实现不得悄悄改变本文定义的核心语义。确需改变时，应先更新本文或形成明确 ADR。

本文使用：

- **MUST / 必须**：V2 架构不变量；
- **SHOULD / 应**：默认方案，无充分理由不偏离；
- **MAY / 可以**：实现选择。

本文不负责最终 DDL、完整 Tool Schema、LangGraph 节点、Prompt、Memory 合并算法、File Parser/Chunk 参数、Scheduler SQL、Push 请求参数和 Eval 阈值；这些进入专项技术设计。

---

# 1. 产品目标与版本边界

“老实人”不是普通 Chatbot，也不是 Todo App 外面套一层聊天界面。

> **用户只表达现实世界中的目标、信息、行动、资料、纠错以及对未来时间或条件的要求；Executive LLM 负责理解现实语义，后端负责把这种理解安全、持久、可追溯地映射成当前现实状态和未来行为。**

用户不需要理解 Thing、Task、Automation、Memory、Tool、LangGraph、Checkpoint、pgvector 等内部概念。

## 1.1 V2 — Backend Complete

V2 聚焦：

- Agent Runtime；
- Personal State；
- Tool / Policy / HITL；
- File / Multimodal / Search / Evidence；
- Long-term Memory；
- Automation / Scheduler；
- Auth / Device / Push；
- REST / SSE Contract；
- Idempotency / Concurrency / Recovery / Audit / Observability / Evals。

V2 前端只需足够验证后端真实能力。

## 1.2 V3 — Client & Product Experience

V3 集中完成 HarmonyOS UI、Today、Things、Chat、Timeline、文件分享、Push 展示、导航、恢复体验、缓存和视觉体系。

## 1.3 Contract Freeze

V2 Freeze 表示：

```text
核心领域语义稳定
+
已有 Contract 的 Breaking Change Freeze
```

V3 MAY 新增 backward-compatible Read Model、查询接口和展示字段，但原则上不得改变 V2 已冻结的核心领域语义、Agent Tool 语义、Run/HITL 生命周期、File Contract 和既有 REST/SSE 含义。

---

# 2. V2 核心取舍

| 议题 | V2 决策 |
|---|---|
| 后端 | 模块化单体，不微服务化 |
| Agent | 单一 Executive 为默认控制中心 |
| LangGraph | Agent orchestration/runtime，不是整个后端 |
| 当前现实 | PostgreSQL 中的 Personal State 为权威 |
| Tool | model-facing capability，不镜像 CRUD |
| State Read | `state.get_overview` / `state.get_thing_context` 聚合读取 |
| State Write | 按业务语义与风险边界拆分 |
| Source | 取消万能 Source Domain，保留 Provenance / Evidence |
| 用户资料 | 稳定内部 `File` + Object Storage |
| 多模态 | 当前附件优先进入模型上下文；历史文件按需检索 |
| Memory | Tiny Profile 自动加载；Semantic/Episodic 按需搜索；显式写入 + durable 后台形成 |
| Automation | 状态视图属于 Personal State；执行由独立 Scheduler 完成 |
| Async Work | PostgreSQL-backed durable work；Redis 只做唤醒/协调加速 |
| Redis | **Non-authoritative Cache & Coordination**：Rate Limit、短生命周期 Cache、Pub/Sub、Worker Wake-up |
| Search | 一个 `search.web` + 独立 Exact URL Retrieval |
| Vector | PostgreSQL + pgvector，不额外引入 Vector DB |

---

# 3. 总体架构与代码依赖

## 3.1 四个平面

```text
Product Domain Plane
User / Thread / Message / Thing / Task / ThingDate
Blocker / Relation / File / Memory / Automation
StateMutation / Timeline / Attention(Read Model)
        │
        ▼
Agent Runtime Plane
Run → Context → Executive → Tool / Policy / HITL
              → Application Use Cases
Checkpoint / Replay / SSE / Tool Ledger
        │
        ▼
Async Work Plane
Run Worker / File Processing / Memory Formation
Scheduler / Condition Watch / Notification / Recovery
        │
        ▼
Platform Plane
Auth / PostgreSQL / pgvector / Redis / Object Storage
Model Gateway / Search / Push / Observability
```

LangGraph 位于 Agent Runtime Plane。

## 3.2 依赖方向

V2 MUST 延续当前仓库的模块化单体边界：

```text
Presentation / Agent / Worker
             ↓
         Application
             ↓
           Domain

Infrastructure 实现 Application ports
```

必须遵守：

- Presentation、Agent、Worker 通过 Application Use Case 改变业务；
- Agent Tool 不得直接访问 ORM、Repository、SQL 或外部凭据；
- Domain 不依赖 FastAPI、LangGraph、SQLAlchemy、模型 SDK、HTTP Client、HarmonyOS；
- API Schema、Application DTO、Domain Entity、ORM Model 分离；
- 外部 Provider 通过 Adapter / Port 接入。

---

# 4. Architecture Invariants

## 4.1 LLM 负责开放式语义，后端负责确定性约束

Executive 负责意图、指代、State Formation、Tool 选择、相关性和最终回答。

后端负责稳定 ID、权威状态、持久化、授权、Policy、Schema、Domain Invariant、幂等、并发、审计、恢复、调度、Push 和 Contract。

> **后端不得用复杂规则系统重复实现开放式语义理解；但必须负责所有可以确定性验证的安全、一致性和业务约束。**

## 4.2 Current User Input 不等于当前已持久化现实

```text
Current User Input
= 本轮最新意图 / 声明 / 纠错

Authoritative Personal State
= 已成功持久化的当前现实
```

用户说“不是 19 号，是 20 号”后，只有对应 Application Use Case 成功持久化，20 号才成为新的权威事实。

Agent 不得把“用户说了”与“系统已经成功执行”混为一谈。

## 4.3 信息权威与 Context Budget 分离

冲突时：

```text
Authoritative Personal State
        >
supplemental_context
        >
Long-term Memory
        >
Thread Summary / Historical Conversation
```

Context 超预算时优先保护：

```text
Current User Message
Current Attachment
Latest Authoritative Tool Result
```

二者是不同概念。

## 4.4 决策权与授权权分离

> **LLM 有决策权，没有授权权。**

是否实际执行，由 Tool metadata、身份、Policy、Automation execution scope、HITL 和 Domain Invariant 共同决定。

## 4.5 PostgreSQL 是 Durable Truth，Redis 是可降级协调层

V2 Production SHOULD 部署 Redis，但 Redis 不成为新的业务权威源。

```text
PostgreSQL + pgvector
= authoritative / durable truth

Redis
= fast / ephemeral / cross-process coordination
```

Redis 适合承担：

```text
distributed rate limit
short-lived cache
cache invalidation
Run / SSE live wake-up
Worker wake-up
```

Redis MUST NOT 成为 Personal State、Long-term Memory、LangGraph Checkpoint、Run Event、Automation 或 Durable Job 的唯一真相来源。

设计目标是：

> **Redis 故障可以造成性能下降或实时性下降，但不能造成业务数据丢失、Run 丢失、Reminder 丢失或状态失真。**


---

# 5. Personal State

Personal State 是**当前现实状态的权威来源**，不保存完整聊天、文件全文、长期经验或模型 Chain-of-Thought。

## 5.1 Thing

Thing：

> **需要跨未来对话持续维护状态的现实事务。**

如软件杯、老实人 V2、论文投稿、雅思备考。

一次提醒、普通小待办、临时问题、Thread 不是 Thing。

## 5.2 supplemental_context

表示当前事务中有价值、但不值得强行结构化的 **Current Soft State**。

它不是 Thread Summary、Memory、File Summary、Deadline 或无限追加日志。

低风险更新仍须通过 Application Use Case 持久化，并遵守 version / audit / policy。

## 5.3 Task

Task：

> **用户未来需要完成或跟进的具体行动。**

Task 是一等对象：

```text
Task.thing_id = nullable
```

支持 Standalone Task 与 Thing-linked Task。

Executive 必须区分“用户自己的 Future Action”和“用户当前要求 Agent 执行的 Action”。

## 5.4 ThingDate

ThingDate 是事务级重要现实时间事实，如 Deadline、比赛日期、答辩日期、Milestone。

MUST 支持时间精度和确定性，概念上至少包括：

```text
precision:
DATE_TIME / DATE / MONTH

certainty:
CONFIRMED / PROBABLE / UNCONFIRMED / DISPUTED
```

重要 Date SHOULD 保留 provenance。

## 5.5 Blocker / Relation

Blocker 表示持续事务当前阻碍。

Relation 仅保存值得显式持久化、对业务有稳定价值的关系，不用于替代 Executive 的语义理解。

## 5.6 StateMutation / Timeline / Attention

```text
StateMutation = 系统级审计事实
TimelineEvent = 对用户有意义的重要历史
Attention     = State 之上的派生 ranking / read model
```

Attention 不是新的业务真相，适合 Today/Home、主动提示和 Automation-triggered Run。

---

# 6. State Formation 与纠错

一句自然语言可以形成多个 durable effect：

```text
“我要参加软件杯，19 号截止，
这周做 Demo，18 号提醒我提交。”

→ Thing
→ ThingDate
→ Task
→ Automation
```

总体流程：

```text
User Turn
  ↓
Executive semantic interpretation
  ↓
是否产生 durable effect？
  ├─ NO  → Respond
  └─ YES → Personal State / Automation / Memory
```

## 6.1 Thing Identification

V2 不建设复杂 Thing Resolver。

```text
active_thing hint
+
recent / active Thing Cards
+
必要时 lexical / vector Top-K recall
        ↓
Executive
        ↓
final thing_id
```

Retrieval 只负责召回。Thing Card 只用于导航；重要写入前应读取最新 `state.get_thing_context`。

## 6.2 Correction / Supersession

Current State MUST 支持纠错，而不是保留多个同等级冲突真相。

```text
Old Fact → superseded / historical
New Fact → current authoritative
```

纠错可能联动 Timeline、Relative Automation、Attention、Evidence 和 Mutation Audit。

## 6.3 多对象写入

- 同一业务 invariant 的写入由 Application 层事务化；
- 多个独立 Tool Call 不假装具有 LLM 级原子性；
- 每次 mutation 都有真实 receipt；
- 部分失败必须按真实结果回报；
- retry 使用 idempotency / expected_version。

---

# 7. Thread、Run 与 Context

## 7.1 Thread

Thread 是可独立清理的短期 conversational workspace，不是长期状态容器，也不强绑定 Thing。

新 Thread 不等于失忆：长期连续性来自 Personal State、Memory、File 和 Automation。

ThreadSummary 只承担 Conversation Compression，不是真实 State 或 Long-term Memory。

## 7.2 Run

```text
Thread = Conversation Container
Run    = 一次 Agent Execution Lifecycle
```

一个 Thread 可以有多个 Run。

概念生命周期：

```text
QUEUED → RUNNING
          ├─ WAITING_FOR_USER → RUNNING
          ├─ COMPLETED
          ├─ FAILED
          └─ CANCELLED
```

同一 Run 的 HITL resume 恢复该 Run checkpoint；新 Run 不把上一 Run Graph State 当业务事实。

## 7.3 ModelContextAssembler

职责：

```text
fetch / select / budget / format
multimodal assembly / provider adaptation
```

不负责业务推理。

Initial Context SHOULD 只自动提供：

1. Instructions / available Tools；
2. current datetime / timezone；
3. current user turn；
4. current attachments；
5. recent messages；
6. Thread Summary；
7. Tiny stable Profile；
8. Relevant Thing Cards。

Full State、Semantic/Episodic Memory、历史文件、Search Results、Attention Candidates 按需 Retrieval。

---

# 8. File、多模态、Search 与 Evidence

## 8.1 输入范围

V2 正式支持：

```text
TEXT / IMAGE / DOCUMENT / AUDIO / URL
```

包括常见图片、截图、PDF、TXT、Markdown、DOCX、PPTX、CSV、XLSX、音频和 HarmonyOS 分享内容。完整视频理解不是 V2 核心能力。

## 8.2 File

取消万能 Source Domain；Message、File、Web Result、Event、Tool Result 保持独立身份。

所有用户上传资料统一作为 `File`：

- MUST 使用老实人稳定内部 `file_id`；
- 二进制原件进入 Object Storage；
- PostgreSQL 保存 metadata、object key、processing status；
- 不以模型 Provider 的 file ID 作为业务主键。

## 8.3 File Processing

保持轻量：

```text
save original
→ MIME / Hash / Metadata
→ light preprocessing
→ READY / FAILED
```

MAY 做 text extraction、page info、chunk/embedding、audio transcription、basic summary，不提前建设复杂 Representation Pipeline。

## 8.4 当前附件与历史文件双路径

当前轮附件：

```text
Current Turn + File
→ ModelContextAssembler
→ native multimodal input / suitable representation
→ Executive
```

具体使用 native input、extracted text 或 selected page images，由 Provider 能力、文件类型、成本和 Context Budget 决定。

历史 / 大型文件按需：

```text
file.search
file.inspect
```

Checkpoint 保存引用，不保存大块 base64 / PDF / image bytes。

## 8.5 Provenance / Evidence

取消 Source Domain 不等于取消证据链。

重要状态 SHOULD 保留轻量 EvidenceRef，例如：

```text
MESSAGE / FILE / WEB
+
id / URL
+
retrieved_at?
+
evidence metadata?
```

多证据需求出现后再升级 `fact_evidence`，不提前建设万能聚合根。

## 8.6 File 生命周期

删除 Thread 只能清理**没有任何 durable reference** 的 File。

Durable reference 包括其他 Thread/Message、Thing、Personal State provenance、Memory provenance、Evidence、Automation context 等。

来源 Message 已删除时，事实本身不自动消失；系统 SHOULD 能表达“来源曾存在，但原内容已不可访问”。

## 8.7 Search 与指定 URL

```text
search.web
= 发现外部信息

Exact URL Retrieval
= 读取用户明确给出的资源
```

二者语义分离。

`search.web` 用参数表达 `ANY / OFFICIAL_FIRST`，但：

```text
Search Strategy ≠ Evidence Certainty
```

`OFFICIAL_FIRST` 不等于 `CONFIRMED`。

---

# 9. Memory

```text
Thread         = short-term conversation
Personal State = current reality
Memory         = cross-thread durable knowledge
```

Memory 不复制会持续变化的 Personal State。

## 9.1 类型与 Retrieval

V2 保留：

```text
PROFILE / SEMANTIC / EPISODIC
```

Retrieval 采用 Hybrid：

```text
Tiny stable PROFILE
→ 少量自动进入 Initial Context

SEMANTIC / EPISODIC
→ Executive 按需 memory.search
```

## 9.2 “记住”不是存储路由指令

用户说“记住……”表示希望长期保留，但不直接决定写 Memory 表。

Executive 必须先判断该信息属于：

```text
Current Personal State
Long-term Memory
或两者
```

例如“记住，截止时间改成 20 号”首先是 ThingDate correction。

## 9.3 Formation

```text
Memory Formation
= Selection + Distillation + Consolidation
```

保留两条写入路径：

```text
Explicit Remember ─┐
                   ├→ MemoryManager
Background Formation┘
```

后台 Formation MUST durable，不能只依赖进程内 queue。

MemoryManager 的 CREATE / UPDATE / MERGE / SUPERSEDE / IGNORE 进入专项设计。

---

# 10. Automation、时间与 Push

Automation：

> **未来某个时间或条件成立时，系统需要主动执行的行为。**

可 standalone，也可关联 Thing / Task。

## 10.1 状态与执行分离

```text
Personal State View
= 用户现在设置了什么

Automation Store + Scheduler
= 未来真实执行
```

## 10.2 Schedule

V2 MUST 支持：

```text
ONCE / RECURRING / RELATIVE / CONDITION
```

RELATIVE 绑定 ThingDate；anchor 变化后可重算。绝对“18 号提醒我”不得随 Deadline 偷偷变化。

CONDITION 由 Scheduler 周期检查，不让一个 LangGraph Run 等待数周。

## 10.3 时间语义

```text
Task Time ≠ ThingDate ≠ Automation Trigger
```

Executive 负责自然语言时间理解；后端负责 normalization、timezone、recurrence、relative trigger calculation 和确定性验证。

数据库绝对时间 UTC；自然语言使用当前 Device timezone；Recurring Automation 保留创建时 timezone 语义。

## 10.4 Execution Scope

Automation-triggered Run 不自动继承交互式 Executive 的全部写权限。

“官网公布名单后告诉我”通常允许 Search、Read State、Evaluate、Notify，不自动授权 Archive、Delete、Modify Deadline 等无关写操作。

可用 Tool / Policy 必须受 Automation 原始 action semantics 和 execution scope 约束。

## 10.5 Push

```text
Automation
→ Occurrence
→ 最新 State
→ 必要时 Agent Run
→ Notification Outbox
→ Huawei Push
→ Device
```

Push Token、权限和订阅状态必须可更新/失效；Push 凭据只存在服务端。

Notification Outbox 的 durable truth 保持在 PostgreSQL；Redis MAY 用于唤醒 Notification Worker，但不能替代 Outbox。

---

# 11. Tool、Policy 与真实执行

必须区分：

```text
Application Use Case Interface
≠
HTTP Product API
≠
Agent-visible Tool API
```

## 11.1 Read / Write

Read 聚合：

```text
state.get_overview
state.get_thing_context
```

Write 保留明确业务语义，不设计 `state.update_everything`。

## 11.2 Tool metadata

每个 Tool SHOULD 定义：

```text
name / description
input / output contract
read-only or mutating
risk / destructive semantics
replay / idempotency semantics
open-world / external interaction
authorization scope
error semantics
Application Use Case binding
```

## 11.3 Policy / HITL

Policy 独立于 LLM。

是否确认综合：

```text
Ambiguity × Impact × Reversibility × Authorization
```

低风险、明确、可逆 mutation MAY 自动执行后回执；高影响、不可逆或真实歧义必须 HITL。

## 11.4 Mutation Receipt 与 Concurrency

只有 persisted Tool Result 成功后，Agent 才能声称“已经完成”。

UI 与 Agent 并发使用：

```text
version / expected_version
```

禁止 silent last-write-wins；冲突后重新读取最新 State 再判断。

---

# 12. Agent Runtime

## 12.1 Single Executive

V2 默认单一 Executive，不预建多 Agent 网络。

未来只有真实 Eval 证明某独立专业能力需要隔离时，MAY 使用：

```text
Executive → Specialist Agent as Tool
```

## 12.2 LangGraph

LangGraph 用于 orchestration、checkpoint、interrupt、resume、durable execution 和 streaming integration。

必须保持：

```text
LangGraph State
≠ Personal State
≠ Long-term Memory
```

Interrupt 恢复可能重新执行当前节点，因此 interrupt 前副作用必须幂等或由可恢复的 durable execution 单元承载。

## 12.3 Tool Execution Ledger

概念上记录：

```text
run_id / action_id / tool
arguments hash / idempotency key
replay policy / status
persisted result / unknown outcome
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

高风险 unknown outcome 不得盲目重放，应通过 ledger、幂等键、查询/对账或人工处理收敛。

## 12.4 ModelGateway

MUST provider-neutral。

业务层不绑定单一 Provider 的 multimodal payload、provider file ID、tool-call protocol 或 response object；Provider 差异由 Adapter / Gateway 吸收。

---

# 13. Async Work、Redis 与恢复

V2 durable work 包括：

```text
Agent Run Worker
File Processing
Memory Formation
Automation Scheduler
Condition Watch
Notification Delivery
Recovery Scanner
```

V2 不引入 Kafka、RabbitMQ、Celery、Temporal 或微服务拆分。

## 13.1 Durable Work Truth

所有不可丢的后台工作以 PostgreSQL durable row 为真相：

```text
PostgreSQL durable row
+ claim
+ lease
+ retry
+ backoff
```

MAY 使用 `FOR UPDATE ... SKIP LOCKED` 实现多个 Worker 的队列式领取。

Worker 崩溃后由 lease expiry + Recovery Scanner 使工作重新进入可处理状态。

## 13.2 Redis Coordination

Redis 在本层只承担**非权威协调与加速**：

```text
job created
↓
PostgreSQL COMMIT
↓
Redis wake-up signal
↓
Worker 立即去 PostgreSQL claim
```

如果 Redis wake-up 丢失或 Redis 暂时不可用：

```text
Worker fallback polling PostgreSQL
↓
任务仍然能够被发现和执行
```

因此：

```text
PostgreSQL
= job truth

Redis
= wake-up / coordination
```

V2 默认不使用 Redis Streams 复制一套 Durable Job Truth；只有未来容量或吞吐证据证明 PostgreSQL durable queue 不足时再升级。

## 13.3 Redis Pub/Sub 的使用边界

Redis Pub/Sub MAY 用于：

- Run Event live wake-up；
- SSE instance fan-out wake-up；
- Worker wake-up；
- cache invalidation。

但 Pub/Sub 是瞬态通知，不承担 replay。

```text
Redis notification lost
≠
durable event lost
```

所有需要重放、恢复和审计的事件仍必须先持久化到 PostgreSQL。

---

# 14. User、Auth、Device 与账号生命周期

```text
External Auth Authority
        ↓
Backend Auth Middleware
        ↓
Internal User
```

V2 MUST 使用稳定内部 `user_id`，业务数据 owner-scoped 到该 ID；Backend 必须验证认证 token，而不是信任客户端 user_id。

Huawei Account 可作为主要正式登录路径。手机号验证码 MAY 作为入口，但具体 SMS 方案受部署区域和服务能力约束，不冻结进核心 Domain。

Device 至少承担：

```text
user-device ownership
push token
timezone
last_seen
```

## 14.1 Rate Limiting

面向正式上线，API / LLM / Search / Auth 等高成本或敏感入口 MUST 有明确限流策略。

V2 SHOULD 使用 Redis 实现跨 API 实例共享的 distributed rate limit，例如：

```text
per-user Run creation
per-user LLM / Search budget
per-IP auth abuse protection
high-frequency public endpoints
```

Redis 故障时必须定义明确降级策略；不得因限流组件故障破坏 durable business state。

## 14.2 Account Lifecycle

账号注销必须覆盖：阻止新 Run、收敛 active Run、停止 Automation、失效 Push Token，并按隐私/审计要求处理 File、State、Memory、Thread 等用户数据。具体顺序进入 Hardening 专项设计。

---

# 15. Thread 删除

> **删除 Thread = 删除对话，不等于撤销对话已经造成的现实变化。**

不自动撤销 Thing、Task、ThingDate、Automation、已形成 Memory。

删除至少包括：

```text
停止新 Run
→ cancel / settle Active Run
→ 清理 Message / Summary
→ 清理 Thread-scoped runtime artifacts
→ cancel 未执行 Memory Formation
→ 清理真正 orphan File
```

已开始的外部副作用不能假设 cancel 会自动撤销，仍由 Tool Ledger / reconciliation 收敛。

---

# 16. API、SSE 与 Contract

V2 Freeze 前冻结：

- REST 核心语义；
- SSE Event Schema；
- Run lifecycle；
- HITL Resume Contract；
- File Contract；
- Error Model；
- Idempotency Contract；
- Personal State Contract。

SSE 必须支持 persistent events、replay / reconnect、terminal status 和稳定 event semantics。

`run_events` 的 durable truth MUST 保存在 PostgreSQL。Redis Pub/Sub MAY 用于跨进程/跨实例即时通知“有新事件”，但客户端 replay 必须依据 PostgreSQL 中已持久化的 event 与 `Last-Event-ID`，不能依赖 Pub/Sub 历史。

```text
Breaking semantic change → Freeze 后原则上禁止
Backward-compatible addition → 允许
既有语义偷换 → 禁止
Deprecation → 显式版本策略
```

当前仓库已有 OpenAPI snapshot 与 SSE JSON Schema 校验方向 SHOULD 保留并扩大到 V2 Contract。

---

# 17. Testing、Observability 与 Evals

```text
Domain / Application invariant
→ deterministic unit test

Repository / API / Tool→Application
→ integration test

Executive semantic behavior
→ agent eval / live-model eval
```

正确结果不要求 Tool trajectory 完全一致。

至少观测 Run、Tool retry、unknown outcome、version conflict、Worker recovery、File processing、Memory Formation、Automation occurrence、Outbox/Push、Search/Provider failure、Redis availability / fallback polling、rate-limit 命中和模型 usage。

不持久化模型 Chain-of-Thought 作为业务数据。

---

# 18. 9 个 Backend Workstreams

| Workstream | V2 必须完成 |
|---|---|
| W1 Runtime | Run、checkpoint、interrupt、resume、cancel、lease、recovery、SSE、ModelGateway、Redis live coordination |
| W2 Tool | Tool 收敛、aggregate read、semantic write、Policy、replay |
| W3 State | Thing、Task、ThingDate、Blocker、Relation、soft state、correction、Mutation、Timeline |
| W4 Context | Thing Card、candidate recall、overview、thing context |
| W5 File | File、Object Storage、attachment、light processing、multimodal、search/inspect、lifecycle |
| W6 Search/Evidence | web search、Exact URL、source preference、evidence/provenance |
| W7 Memory | Profile/Semantic/Episodic、search、remember/forget、durable formation、consolidation |
| W8 Automation | 4 schedule、occurrence、execution scope、condition watch、outbox、Push |
| W9 Hardening | formal auth、ownership、account lifecycle、Redis rate limit/cache、concurrency、idempotency、audit、errors、Contract、Evals |

---

# 19. Backend Freeze Gates

## Gate A — User Journey

用真实自然语言、真实文件、真实提醒走通完整用户旅程。

## Gate B — Safety & Consistency

至少保证：

- State 胜过 stale Memory；
- 未持久化声明不被误说成已执行；
- UI / Agent 不 silent overwrite；
- 高影响歧义不误执行；
- retry 不重复副作用；
- unknown outcome 不盲目重放；
- Thread 删除不撤销现实；
- Automation 不越权。

## Gate C — Resilience

主动测试 LLM/Tool timeout、Worker/process crash、Push/Search/File/Memory failure、Redis outage、version conflict、network disconnect、外部副作用崩溃窗口和 lease 过期。

其中 Redis outage 必须验证：durable job、Run、Automation、Run Event、Memory 和 Personal State 不丢失；Worker 能通过 PostgreSQL fallback polling 继续恢复工作。

## Gate D — Agent Quality

覆盖 Thing/Task/Automation Formation、Thing Resolution、soft state、Tool Selection、State Correction、Memory、File、Search/URL、时间、Relative/Condition Automation、歧义和最终回答。

每个 Gate MUST 有可执行测试和明确 pass/fail 标准；具体阈值进入 Eval 专项文档。

---

# 20. V2 明确不做

- 微服务拆分；
- Kafka / RabbitMQ / Temporal / Celery；
- 独立 Vector DB；
- 把 Redis 作为 Personal State、Memory、Checkpoint、Run Event 或 Durable Job 的权威存储；
- V2 默认使用 Redis Streams 再复制一套 durable queue / event truth；
- 企业 Organization / Tenant / RBAC / IAM；
- 预建多 Agent 网络；
- 完整 Calendar Domain；
- 完整视频理解；
- 复杂 File Representation Pipeline；
- 复杂规则化 Thing Resolver；
- Attention 作为权威状态；
- 复杂前端视觉打磨。

只有真实容量、复杂度或 Eval 证明当前路线不足时，后续版本才升级。

---

# 21. Logical Data Landscape

> 本节是逻辑版图，不等于最终物理表名或 DDL。

```text
IDENTITY
users / devices / external_auth_identities?

CHAT
threads / messages / message_attachments

PERSONAL STATE
things / tasks / thing_dates / blockers / relations
state_mutations / timeline_events

FILES & EVIDENCE
files / file_chunks? / thing_files / evidence refs?

MEMORY
memories / memory provenance

AUTOMATION
automations / occurrences / notification_outbox

AGENT RUNTIME
runs / run_events / tool_executions

ASYNC / PLATFORM
durable_jobs / processing / lease / recovery metadata
```

Redis 不进入 durable logical schema；其 key 只承载可重建的 ephemeral state，例如 rate-limit counter、cache、pub/sub channel 和 wake-up signal。

Attention 保持 derived read model。

---

# 22. 从当前 V1 收敛到 V2

当前仓库已经具备模块化单体、Personal State、Memory、Automation/Attention、Thread/Run/SSE、LangGraph Executive、Tool/Policy 和 Contract 基础。

V2 不是推倒重写，而是定向收敛：

```text
较多表级 State Tool
→ 聚合 Read + 业务语义 Write

重型 Source
→ File + 独立对象 + Provenance/Evidence

较重 Initial Prefetch
→ 轻量 Context + 按需 Retrieval

Provider-specific input
→ ModelContextAssembler + Provider-neutral Gateway

进程内 durable work 缺口
→ PostgreSQL-backed durable work

缺少跨进程实时协调 / 统一限流 / 短生命周期 Cache
→ Redis non-authoritative Cache & Coordination

开发态固定身份
→ 正式 Auth + Internal User + Device

Recording Push
→ Huawei Push 真实后端闭环

CONDITION stub
→ Scheduler-driven Condition Watch
```

迁移优先保护已持久化业务数据、Stable ID、幂等与审计、可回滚 Migration 和现有确定性测试。

---

# 23. 后续专项文档

1. `老实人_Agent_Runtime技术设计_v2.x.md`
2. `老实人_Personal_State与Memory技术设计_v2.x.md`
3. `老实人_Tool_API_Policy技术设计_v2.x.md`
4. `老实人_File_Multimodal_Search_Evidence技术设计_v2.x.md`
5. `老实人_Automation_Scheduler_Push技术设计_v2.x.md`
6. `老实人_Backend_V2开发实施路线_v2.x.md`
7. `老实人_Backend_V2_Eval与验收设计_v2.x.md`

讨论总结、开发报告、ADR、CURRENT_IMPLEMENTATION 保留各自历史/现状角色，不与正式架构基线混用。

---

# 24. 设计依据与官方资料

## 24.1 项目内部依据

本文优先继承：

- 《老实人架构设计｜当前页面对话讨论总结》；
- 《老实人 Backend V2 总体架构设计 v2.0》；
- 当前仓库 `README.md`、`AGENTS.md`、`docs/CURRENT_IMPLEMENTATION.md`。

权威关系：

```text
本轮确认的 V2 架构结论
>
旧 v1.0 目标设计
>
当前 V1 临时实现形态
```

当前实现是迁移起点，不反向限制 V2 目标架构。

## 24.2 外部官方资料

以下资料用于校验技术路线，不替代项目自己的领域决策：

- LangGraph Overview  
  https://docs.langchain.com/oss/python/langgraph/overview
- LangGraph Interrupts  
  https://docs.langchain.com/oss/python/langgraph/interrupts
- LangGraph Memory Overview  
  https://docs.langchain.com/oss/python/concepts/memory
- LangGraph Functional API / durable task guidance  
  https://docs.langchain.com/oss/python/langgraph/functional-api
- Model Context Protocol — Tools  
  https://modelcontextprotocol.io/specification/2025-11-25/server/tools
- OpenAI Responses API（仅作为 provider multimodal/tool 能力参考）  
  https://developers.openai.com/api/reference/cli/resources/responses/methods/create
- PostgreSQL 17 `SELECT` / `FOR UPDATE ... SKIP LOCKED`  
  https://www.postgresql.org/docs/17/sql-select.html
- Redis Pub/Sub — delivery semantics  
  https://redis.io/docs/latest/develop/pubsub/
- Redis Rate Limiter  
  https://redis.io/docs/latest/develop/use-cases/rate-limiter/
- Redis Use Cases — cache / job queue 等能力参考  
  https://redis.io/docs/latest/develop/use-cases/
- AppGallery Connect Auth — token verification  
  https://developer.huawei.com/consumer/en/doc/appgallery-connect-Guides/sever-rest-verifytoken-0000001323246818
- AppGallery Connect Auth — account lifecycle  
  https://developer.huawei.com/consumer/en/doc/appgallery-connect-Guides/agc-auth-client-rest-process-0000001374177933
- HarmonyOS Push Kit `pushService`  
  https://developer.huawei.com/consumer/en/doc/harmonyos-references-V13/push-pushservice-V13
- HarmonyOS Push Kit Integration Specifications  
  https://developer.huawei.com/consumer/en/doc/harmonyos-guides-V13/push-specification-V13

---

# 25. Backend V2 一句话定义

> **老实人 Backend V2 是一个以 Executive LLM 为开放式语义决策核心、以 Personal State 为当前现实权威、以 File 保存原始资料、以 Memory 保存跨 Thread 长期知识、以 Automation 承担未来主动行为，并通过 LangGraph Runtime、Application Use Cases、PostgreSQL durable truth、Redis 非权威协调、Tool/Policy/HITL、Evidence、Push、Recovery 与 Evals 将这些理解安全、持久、可恢复地落到现实中的个人 Agent 后端。**

用户只负责表达现实。  
Executive 负责理解。  
后端负责让这种理解**真实发生，而且发生得安全、一致、可追溯、可恢复**。
