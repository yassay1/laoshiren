# 老实人 Personal State 与 Memory 技术设计 v2.2

> **文档状态：正式开发专项基线（Baseline）**  
> **版本：v2.2**  
> **适用范围：老实人 Backend V2.2**  
> **目标平台：真实上线 HarmonyOS App 的个人 Agent 后端**  
> **权威持久化：PostgreSQL + pgvector**  
> **协调层：Redis（non-authoritative cache / coordination only）**  
> **本文不包含：最终 SQL DDL、具体 Prompt、最终 Tool Schema、最终 REST Contract、未来版本能力**

---

## 0. 文档目的

本文定义老实人 Backend V2.2 中 **Personal State 与 Long-term Memory 的正式产品语义、领域边界、状态形成、纠错、并发、证据、生命周期与逻辑数据模型**。

本文不是讨论总结，而是后续开发工作的专项基线。后续 Tool / API / Policy / Repository / Migration / Eval 设计必须与本文兼容。

本文必须同时回答：

1. 老实人如何表示“用户现在的现实是什么”；
2. 用户一句自然语言如何形成一个或多个 durable effect；
3. 现实如何被纠正，而不是叠加成多个冲突真相；
4. 什么信息属于长期 Memory，什么绝对不属于；
5. 新 Thread 为什么不会失忆；
6. Memory 为什么永远不能覆盖 Current State；
7. UI、Agent、Automation 并发修改时如何保证一致；
8. 删除 Thread、File、Thing、Memory、Account 时分别发生什么；
9. 用户半年后重新使用时，为什么系统仍然能正确理解用户；
10. 为什么数据不会随着使用越来越脏。

---

# 1. 上位约束与继承关系

本文直接继承以下 Backend V2.2 基线，不重新争论：

- 《老实人_Backend_V2_总体架构设计_v2.2_正式基线版》
- 《老实人_Agent_Runtime技术设计_v2.2》
- 《老实人_上线最小用户与通知支持设计_v2.2》

核心上位约束：

```text
PostgreSQL + pgvector
= authoritative / durable truth

Redis
= non-authoritative cache / coordination / wake-up
```

不得把以下权威数据迁移为 Redis truth：

- Personal State；
- Long-term Memory；
- LangGraph Checkpoint；
- Run Event；
- Automation；
- Durable Job。

同时保持：

```text
LangGraph State
≠ Personal State
≠ Long-term Memory
```

LangGraph 承担 Agent Runtime、checkpoint、interrupt、resume、durable execution；业务现实仍由老实人 Application / Domain + PostgreSQL 管理。

---

# 2. V2.2 明确不做

本文不引入：

- 独立 Vector DB；
- Elasticsearch / 独立搜索服务；
- 复杂 Knowledge Graph；
- 万能 Source Domain；
- Kafka；
- Temporal；
- 新微服务拆分；
- LangSmith；
- Generic Relation Graph；
- 大型 RAG Platform；
- “所有信息一个 JSONB”式万能 State；
- “每条消息都创建 Thing”；
- “每轮自动搜索所有 Memory”；
- “用户说记住就直接 INSERT Memory”；
- “向量相似就是最终语义判断”；
- “所有实体都设计复杂状态机”。

---

# 3. 核心心智模型

老实人必须把以下概念严格分开：

```text
Thread / Message
= 这一次聊了什么

ThreadSummary
= 这一次长对话被压缩后的短期上下文

Personal State
= 用户现在现实情况是什么

Long-term Memory
= 跨 Thread 值得长期保留的知识

File
= 原始用户资料

Evidence / Provenance
= 状态或记忆从哪里来、由什么支持

StateMutation
= 系统级状态修改审计

TimelineEvent
= 用户有意义的状态变化历史

Automation
= 未来某个时间或条件成立时系统主动执行的行为
```

以上对象可以互相关联，但不得互相替代。

---

# 4. 信息权威顺序

当信息存在冲突时，当前现实的权威顺序为：

```text
Authoritative Personal State
>
supplemental_context / Current Soft State
>
Long-term Memory
>
Thread Summary
>
Historical Conversation
```

File / Search / Evidence 是原始资料与外部依据，其是否改变 Current State 取决于 Executive 理解与正式 Application mutation，而不是“查到了就自动变成现实”。

**Frozen Rule：**

> 如果旧 Memory、旧 Thread 或旧 File 内容与 Current Personal State 冲突，Current Personal State 必须胜出。

---

# 5. Personal State 的正式定义

Personal State 是：

> **用户当前现实状态的权威领域模型。**

Personal State 不是一张万能 `personal_state` 大宽表。

V2.2 的 Personal State 由多个明确业务对象组成：

```text
Personal State
│
├── Thing
├── Task
├── ThingDate
├── ThingContextEntry   # Current Soft State
├── Blocker
└── Automation State View
```

其中 Automation 的“用户当前设置了什么”可以进入 Personal State read model，但真正未来触发仍属于独立 Automation Store + Scheduler。

---

# 6. Personal State Overview：产品展示面，不是权威表

HarmonyOS App 应提供一个统一的 **Personal State Overview**，向用户展示“老实人现在如何理解我”。

用户不需要看到 `Thing / SEMANTIC / Blocker` 等后端术语。

产品上可以表现为：

```text
我的状态

正在进行
- 软件杯
- 老实人 V2

今天 / 待办
- 取快递
- 完成 Demo

重要日期
- 9/19 软件杯截止

当前情况
- 老师目前更关注 Demo

当前阻碍
- 等待老师提供实验数据

老实人长期记得的我
- 技术设计优先参考官方资料
- 通常晚上集中写代码
```

因此：

```text
PersonalStateOverview
= Application Read Model
≠ authoritative database entity
```

它由 Application 层聚合 Thing、Task、ThingDate、ThingContextEntry、Blocker、Automation，以及少量适合用户查看的 Memory。

---

# 7. UI 修改权限

Personal State 的主要维护方式仍是自然语言 + Executive。

UI 只开放**高频、低歧义、可逆**操作。

## 7.1 UI MAY 直接修改

例如：

- Thing Rename；
- Thing Archive / Restore；
- Task Complete；
- Task Cancel；
- Blocker Resolve；
- 简单 Current Soft State 修正；
- Automation Disable / Cancel；
- Memory Forget / 简单纠正。

所有 UI mutation 仍必须经过 Application Use Case，遵守：

```text
ownership
version / expected_version
policy
audit
derived effects
```

## 7.2 复杂语义变化主要通过 Agent

例如：

- Primary Deadline correction；
- 模糊时间修改；
- Thing Merge；
- 复杂事务结构调整；
- Blocker 形成；
- 复杂 provenance / evidence 判断；
- 一句话多对象联动。

禁止提供一个万能 UI 编辑器直接修改整个 Personal State JSON。

---

# 8. Personal State Domain Boundary

以下真实用户输入在 V2.2 中应按其现实语义归类：

| 用户表达 | 默认归属 | 理由 |
|---|---|---|
| “我要参加软件杯。” | Thing | 持续事务，未来仍值得问进展 |
| “软件杯 19 号截止。” | ThingDate | 当前重要现实时间事实 |
| “老师说最好先做 Demo。” | ThingContextEntry | 当前策略/软状态，不强行结构化成 Task |
| “我觉得这个项目有点难。” | Thread，通常不持久化 | 瞬时感受，不足以形成 durable fact |
| “我平时喜欢晚上写代码。” | PROFILE Memory | 稳定、跨 Thread、有未来复用价值 |
| “上次比赛我因为忘记提交错过了。” | EPISODIC Memory | 过去经历具有未来复用价值 |
| “这周把 Demo 做完。” | Task | 用户未来要完成的具体行动 |
| “帮我查一下官网。” | Current Agent Action | 用户要求 Agent 现在执行，不是 Task |
| “官网公布结果以后告诉我。” | Automation | 未来系统行动，不是用户未来行动 |

---

# 9. Thing

## 9.1 定义

Thing 表示：

> **需要跨未来对话持续维护状态的现实事务。**

判断心智：

> 这件事以后是否仍然值得问：“现在进展到哪了？”

典型 Thing：

- 软件杯；
- 老实人 V2；
- 论文投稿；
- 雅思备考；
- 求职；
- 旅行计划。

不应创建 Thing 的场景：

- 一次提醒；
- 普通小待办；
- 临时问题；
- 单个 Chat Thread；
- 纯 Todo Folder。

Executive 负责最终 Thing Formation；不建设复杂规则型 ThingResolver。

## 9.2 Thing lifecycle

V2.2 Thing 业务状态冻结为：

```text
ACTIVE
COMPLETED
CANCELLED
```

不增加复杂状态机。

## 9.3 Archive 与业务状态分离

Archive 表示用户当前是否希望在默认界面持续关注该 Thing。

```text
status = ACTIVE | COMPLETED | CANCELLED
archived = true | false
```

Archive 不得自动 Cancel Task、Cancel Automation、修改 ThingDate、删除 File 或修改 Memory。

## 9.4 Reactivation

Thing MAY 重新激活：

```text
COMPLETED → ACTIVE
CANCELLED → ACTIVE
```

## 9.5 Duplicate / Merge

候选召回可使用 active hint + recent Thing Cards + lexical/vector recall；retrieval 只负责召回，Executive 负责最终判断。

禁止通过单一 vector similarity threshold 自动 merge。

若重复 Thing 已经创建，允许：

```text
Thing B
merged_into_thing_id = Thing A
```

A 成为 canonical Thing；B 退出 Current State，但保留 redirect/tombstone。Merge 是 identity correction，不是 Thing lifecycle status。

---

# 10. Task

## 10.1 定义

Task 表示：

> **用户未来需要完成或跟进的具体行动。**

Task 是一等对象：

```text
Task.thing_id = nullable
```

支持 Standalone Task 与 Thing-linked Task。

## 10.2 Task lifecycle

V2.2 最小状态：

```text
TODO
DONE
CANCELLED
```

## 10.3 Task Time

Task 时间表达“用户计划什么时候做”或“最晚什么时候完成”。概念上允许：

```text
scheduled_at / scheduled_date
due_at / due_date
```

具体字段结构留实现阶段。

必须保持：

```text
Task Time
≠ ThingDate
≠ Automation Trigger
```

## 10.4 Reminder 不替代 Task

用户“明天下午三点提醒我取快递”包含：

```text
User future action → Task("取快递")
System future action → Automation(15:00 reminder)
```

而“官网公布名单以后告诉我”只有 Automation，不创建 Task。

## 10.5 CreateTaskWithReminder

当 Task + Reminder 构成一个不可拆用户业务意图时，应由一个 Application Use Case 原子完成，例如 `CreateTaskWithReminder`。

这不是让 LLM 拥有跨 Tool 全局事务，而是把明确业务 invariant 放入 Application transaction。

## 10.6 Recurring Task

V2.2 产品能力 **MUST 支持周期 Task**。

“我每周日都要写周报”应成为可完成、可推进到下一周期的 Task，而不是伪装成 recurring notification。

具体采用 recurrence spec、template + occurrence 或其他最小实现，留实施阶段冻结；但必须保持：

```text
Recurring Task
≠ Recurring Automation
```

---

# 11. ThingDate

## 11.1 定义与类型

ThingDate 表示持续事务中的重要现实时间事实。

V2.2 type 冻结为：

```text
DEADLINE
EVENT
MILESTONE
```

更细显示使用 label，不新增大量 type。

## 11.2 Precision

```text
DATE_TIME
DATE
MONTH
```

用户只说“大概 9 月截止”时不得强行落成具体某一天。

## 11.3 Certainty

```text
CONFIRMED
PROBABLE
UNCONFIRMED
DISPUTED
```

certainty 表达事实确定程度，不是模型自信分数。

## 11.4 Timezone / Local Semantics

数据库绝对时间使用 UTC；自然语言解释使用当前 Device timezone。

## 11.5 Correction

ThingDate correction 默认采用稳定 ThingDate ID + versioned current update。

例如 D01 从 9/19 v3 更新为 9/20 v4。Current State 中只存在 20 号这一套当前真相；旧值通过 StateMutation / TimelineEvent 保留。

“superseded”是历史语义，不要求每个 ThingDate 历史版本都保留为同等级 current row。

## 11.6 Relative Automation

Relative Automation 绑定稳定 `anchor_thing_date_id + offset`。Deadline correction 后重新计算 trigger；绝对“18 号提醒我”不得随 Deadline 改动。

---

# 12. ThingContextEntry：Current Soft State

旧的 `supplemental_context` 正式收敛为少量、当前仍成立、但不值得强行结构化的 Current Soft State entries。

推荐领域名：`ThingContextEntry`。

禁止一个巨大 text blob 不断 append。推荐：

```text
label: 老师关注
content: 当前更关注 Demo 是否能完整跑通
```

ThingContextEntry 表示 Current State，不是日志。同一语义发生变化时更新 current entry，version++；旧值进入 Mutation / Timeline。

若 Soft State 后来获得明确业务语义，应形成对应结构化对象，例如“老师建议先做 Demo”可以是 ContextEntry，而“这周把 Demo 做完”形成 Task。

不冻结数据库硬数量限制，但 Application / Agent policy SHOULD 保持每个 Thing 的 active soft entries 很小。

---

# 13. Blocker

Blocker 表示：

> **当前正在实质性阻止或显著延迟某个持续事务推进、值得未来再次检查是否解除的现实障碍。**

判断条件：

```text
① 是当前现实
② 正在阻止 / 显著延迟 Thing 推进
③ 以后值得问“这个卡点解决了吗？”
```

V2.2 生命周期仅：

```text
OPEN
RESOLVED
```

Blocker MUST 属于 Thing，不建设 standalone Blocker。

“老师还没给实验数据，所以论文实验做不了”是 Blocker；“这个项目有点难”通常不是。

---

# 14. Relation 策略

V2.2 **不建设 Generic Relation Entity / Knowledge Graph**。

以下明确关系直接使用 native domain references：

```text
Task → Thing
Automation → Thing
Automation → Task
Automation → ThingDate
File ↔ Thing
Memory → related Thing（optional）
Thing merge redirect
```

跨 Thing `DEPENDS_ON` 等关系仅保留未来能力边界，只有真实 Eval 证明稳定收益时才实现。

---

# 15. State Formation

## 15.1 总流程

```text
User Turn
   ↓
Executive semantic interpretation
   ↓
Candidate Durable Effects
   ↓
dependency ordering
   ↓
Application mutations
   ↓
Durable Mutation Receipts
   ↓
Current State
   ↓
Final Response
```

Candidate Durable Effects 是当前 Run 的执行理解，不是 Personal State，不新增独立 CandidateEffect 业务表。

只有 Application mutation 成功 COMMIT 后，才成为 authoritative reality。

## 15.2 一句话多个 durable effect

用户：

> “我要参加软件杯，19号截止，这周做 Demo，18号提醒我提交。”

可能形成：

```text
Thing
ThingDate
Task
Automation
```

Executive 负责语义理解、指代、Thing 判断、candidate effects 与 Tool selection；Backend 负责 ID、Schema、version、transaction、concurrency、idempotency、policy、audit、authorization 与 recovery。

## 15.3 Mutation 默认顺序执行

若后续 mutation 依赖前序 receipt：

```text
create Thing
↓ thing_id
set ThingDate
↓ date_id
create Task
create Automation
```

Read MAY 并行；mutation 默认顺序执行。

---

# 16. Transaction Boundary 与 Partial Success

核心原则：

> **同一个 User Turn 可以部分成功；同一个不可拆业务 invariant 不允许部分成功。**

如果中间状态一旦暴露就会使用户完整意图本身失效，应在同一 Application Use Case 内事务化。

例如 `CreateTaskWithReminder` 中 Task 与 linked Reminder 属于同一个不可拆业务意图。

但软件杯整句话中的 Thing、ThingDate、Task、Automation 并不天然要求一个总事务。若 Task 创建失败而 Thing / Deadline / Automation 已成功，这些成功现实不应因一个独立 effect 失败而 rollback。

---

# 17. Mutation Receipt

Final Response 必须依据 persisted receipts，而不是依据 Executive 原始计划。

Mutation Receipt 是 Application mutation 的标准结果语义，概念上至少能表达：

```text
action_id
status
entity_type
entity_id
previous_version?
new_version?
mutation_id?
derived_effects?
error?
```

只有 persisted SUCCESS receipt 返回后，Agent 才能声称“已经创建 / 已经修改 / 已经完成”。

若一句话出现部分失败，Assistant 必须准确汇报真实结果，而不是说“都完成了”或笼统说“操作失败”。

---

# 18. Correction / Supersession

V2.2 将 correction 分为三类。

## 18.1 Attribute correction

例如 Deadline 19 → 20：同一实体稳定 ID，更新 current value，version++。

## 18.2 State correction

例如 Task DONE → TODO：用户说“我刚才点错了，Demo 其实还没做完”，应更新同一 Task，不新建重复 Task。

## 18.3 Identity correction

两个 Thing 其实是同一个现实事务时，使用 canonical Thing + merge redirect，不保留两个同等级 current entity。

## 18.4 Supersession 语义

Old Fact 必须成为 historical / superseded 语义，New Fact 才是 current authoritative。

但不要求所有 Domain 表统一加入 `is_current / superseded_by / superseded_at`。历史优先由 StateMutation / Timeline 承载；只有真正需要 canonical redirect 的实体（如 Thing merge、Memory consolidation）保留显式 redirect/supersede。

---

# 19. StateMutation

StateMutation 表示：

> **一个有业务意义的系统级状态修改审计事实。**

不是每一条 SQL UPDATE。

例如 `set_deadline` 内部可能同时修改 ThingDate、version、derived read model 与 relative automation，但仍是一个业务 mutation。

StateMutation 应能回答：

```text
谁
何时
通过什么 channel
把什么
从什么
改成什么
为什么
基于什么 provenance
来自哪个 Run / action
```

概念字段可包括：

```text
mutation_id
user_id
actor
channel
entity_type
entity_id
operation
before
after
version_before
version_after
reason?
provenance
run_id?
action_id?
created_at
```

`before / after` 使用 JSONB 是合理的，因为它们是 heterogeneous audit payload，不是 authoritative domain。

## 19.1 Actor / Channel

应区分用户意图与执行通道。

UI 点击完成：

```text
actor = USER
channel = UI
```

用户在聊天说“Demo 做完了”：

```text
semantic actor = USER
channel = AGENT
```

系统 derived mutation：

```text
actor = SYSTEM
channel = AUTOMATION / WORKER
```

不得把所有 Agent Tool mutation 都简单记为 `actor = AGENT`。

---

# 20. TimelineEvent

TimelineEvent 表示：

> **用户真正关心的历史变化。**

StateMutation 与 TimelineEvent 严格分离。

通常值得 Timeline：

- Thing 开始；
- Thing completed / cancelled / reactivated；
- Deadline 重要修正；
- Task 完成；
- Blocker 出现 / 解除；
- Thing merge；
- 重要阶段变化。

通常只留 audit：

- 标题错别字修复；
- Soft State 轻微措辞整理；
- ranking 重算；
- embedding 更新；
- 内部 metadata refresh。

Timeline 是否形成由 Application / Domain policy 决定，不让 LLM 每次自由决定。

---

# 21. Provenance 与 Evidence

## 21.1 Provenance

回答：

> **这个状态 / 记忆是从哪里来的？**

可能来源：

```text
MESSAGE
FILE
WEB
UI
TOOL_RESULT
AUTOMATION
SYSTEM
```

## 21.2 Evidence

回答：

> **有什么材料支持这个事实？**

例如 ThingDate“软件杯截止 9/19”可以由用户消息形成，同时由官方比赛页面支持。

Provenance 与 Evidence 不是同一个概念。

## 21.3 V2.2 轻量策略

重要 State SHOULD 有 primary provenance。

需要外部支持的事实 MAY 有 primary evidence。

不强制所有事实从第一天使用 N:N multi-evidence；多证据真实需求出现后再升级 `fact_evidence`。

禁止重新建设万能 Source Domain。

## 21.4 不使用通用 confidence

不为每个 State Fact 强加 `confidence / retrieved_at`。

只有领域真的需要才保存。例如 ThingDate 有 certainty；Web evidence 才有 URL、retrieved_at、title、locator；Task“取快递”没有通用 confidence 的产品意义。

---

# 22. Concurrency

## 22.1 Optimistic Concurrency

以下重要 mutable state MUST 使用：

```text
version
expected_version
```

包括 Thing、Task、ThingDate、ThingContextEntry、Blocker、Automation、Memory。

禁止 silent last-write-wins。

## 22.2 Version Conflict

若 Agent 基于 Task TODO v3 写入，但 UI 已先将它更新为 DONE v4，Application 必须返回 `VERSION_CONFLICT`。

正确流程：

```text
VERSION_CONFLICT
↓
re-read latest State
↓
Executive re-evaluate original user intent
↓
no-op / new mutation / ask user
```

禁止 blind retry old write。

## 22.3 PostgreSQL isolation

V2.2 默认：

```text
Read Committed
+
application-level expected_version
```

同一短事务中确实需要保护多行 invariant 时 MAY 使用必要 row lock；只有少数真正复杂一致性问题才考虑 Serializable，并必须准备完整事务重试。

不得默认全系统 Serializable。

## 22.4 禁止长事务等待模型 / 用户

禁止：

```text
BEGIN
SELECT ... FOR UPDATE
↓
LLM thinking / HITL 等待
↓
COMMIT
```

数据库 transaction 和 row lock 必须短。

---

# 23. Relative Automation 并发

Relative Automation 必须在执行前重新验证最新 anchor。

例如 ThingDate D1 = 9/19 v3，Automation = deadline - 1 day。Scheduler 已生成旧 occurrence 时，用户把 Deadline 改成 9/20 v4。

执行旧 occurrence 前：

```text
read latest D1
↓
anchor version changed
↓
old trigger stale
↓
SKIP / RESCHEDULE
```

不能依赖 Redis wake-up 顺序保证正确性。PostgreSQL durable truth 决定最终语义。

---

# 24. Idempotency 与 Crash Recovery

所有重要 mutation 必须携带稳定：

```text
action_id / idempotency_key
```

场景：Application COMMIT 成功，但进程在 Tool response 返回前崩溃。

恢复后同一 action 再执行：

```text
same action_id
↓
Tool Ledger / mutation result lookup
↓
return previous durable receipt
```

不能重复创建实体。

工程语义：

```text
at-least-once execution
+
idempotent replay
+
unknown-outcome protection
```

不宣称 exactly-once。

---

# 25. Long-term Memory

Memory 表示：

> **不属于当前权威现实状态，但值得跨 Thread 长期保留，并能改善未来理解、判断或回答的信息。**

V2.2 仅保留：

```text
PROFILE
SEMANTIC
EPISODIC
```

不增加 Procedural Memory。系统 Prompt、Agent Policy、Tool Instructions、Skill 等属于系统配置，不属于用户 Long-term Memory。

---

# 26. PROFILE Memory

PROFILE 保存稳定、跨多数对话有价值的用户偏好、习惯与交互方式，例如默认语言、技术资料偏好、长期工作习惯。

PROFILE 不等于所有用户兴趣的无限档案。

---

# 27. SEMANTIC Memory

SEMANTIC 保存跨 Thread 有复用价值的稳定事实、知识与长期结论。

若某信息仍属于一个 Active Thing 的“当前策略 / 当前现实”，应优先留在 Personal State。

例如“老实人 V2 当前先冻结 Backend，再做 Client”在 Thing ACTIVE 期间优先属于 ThingContextEntry，而不是 Semantic Memory。

---

# 28. EPISODIC Memory

EPISODIC 保存过去有未来复用价值的经历、结果和经验。

理想语义：

```text
Situation
→ Action / Event
→ Outcome
→ Useful Lesson
```

“上次比赛因忘记最终提交而错过”是合适的 Episodic Memory；“某天用户聊了软件杯”不是。

---

# 29. 什么绝对不应该进入 Memory

默认不得直接 Formation：

- Current Task；
- Current Deadline；
- Current Blocker；
- Current ThingContextEntry；
- Thread Summary；
- 聊天全文；
- File 全文；
- File Summary 的简单复制；
- 一次性 Web Search 结果；
- 瞬时情绪；
- LLM Chain-of-Thought；
- Credential / Password / Token。

Background Formation 对敏感个人信息必须更保守；具体敏感数据 policy 留 Privacy / Policy 实施阶段冻结。

---

# 30. Explicit Remember

用户说“记住……”表示 retention intent，不表示 `INSERT memory`。

Executive 必须判断真正归属。

- “记住我喜欢晚上学习。” → PROFILE Memory。
- “记住，软件杯截止日期改成 20 号。” → ThingDate correction，不复制 Deadline Memory。
- “记住我上次比赛忘记提交了。” → EPISODIC Memory。
- “记住老师现在最关心 Demo。” → ThingContextEntry。

---

# 31. Memory 写入双路径

V2.2 保留：

```text
Explicit Remember
+
Background Formation
```

但两条路径最终都必须进入 MemoryManager，不允许任何路径绕过 MemoryManager 直接写 Active Memory。

---

# 32. Background Memory Formation

## 32.1 不每轮调用昂贵 LLM

禁止 every Run → another Memory Formation LLM call。

## 32.2 推荐机制：hint + idle coalescing

Executive 在正常理解 User Turn 时可产生轻量 `memory_formation_hint`。它只表示“这一轮似乎出现值得后续检查的长期信息”，不是 Memory Candidate，也不是 Memory。

Run 完成后：

```text
hint = true
↓
upsert / coalesce PostgreSQL MemoryFormationJob
↓
short idle window
↓
Worker
```

一段连续对话 burst 尽量合并为一次 Formation。具体 idle window 不在本文冻结。

## 32.3 补充触发

V2.2 MAY 使用：累计 N 个 meaningful turns 后 catch-up、Thing completed/cancelled 等重要 lifecycle event、用户显式触发。具体阈值留 Eval 调参。

## 32.4 Durable Work

MemoryFormationJob truth MUST 在 PostgreSQL。Redis MAY wake Worker；即使 Redis wake-up 丢失，也必须通过 PostgreSQL fallback polling 最终发现 Job。

---

# 33. Formation Pipeline

```text
MemoryFormationJob
↓
read source message range
+
latest relevant Personal State
+
small existing relevant Memory set
↓
Selection
↓
Distillation
↓
Memory Candidates
↓
MemoryManager
↓
commit
```

Formation 模型不能直接 INSERT Memory。Formation 时读取 Latest Personal State 的重要目的之一是防止把 Current State 复制成长 Memory。

---

# 34. MemoryManager

MemoryManager 是 Long-term Memory 的唯一数据洁净写边界。

对外动作收敛为：

```text
CREATE
REVISE
CONSOLIDATE
IGNORE
```

用户产品动作另有：

```text
FORGET
```

`SUPERSEDED` 是 Memory lifecycle outcome，而不是必须暴露成平级 Manager command。

## 34.1 CREATE

没有合理现有 Memory，且 candidate 值得长期保留。

## 34.2 REVISE

同一长期知识被修正或细化。优先保持稳定 memory_id + version++。

## 34.3 CONSOLIDATE

多个 Active Memory 实际表达同一长期知识时，选定 canonical Memory，重新 distill；其他 Memory 变为 SUPERSEDED 并指向 canonical。

## 34.4 IGNORE

包括：candidate 属于 Current State、信息不稳定、无未来价值、已有 Active Memory 已完整表达、candidate stale、或 candidate 与用户明确 Forget 冲突。

## 34.5 MemoryManager 并发写边界

Explicit Remember 与 Background Formation 可能同时尝试写入同一用户的近似 Memory。两条路径都必须在 **commit 前读取最新 ACTIVE Memory 并重新 reconcile**。

MemoryManager MUST 提供一个短时间、可恢复的 reconciliation serialization scope，至少保证同一用户同一批相关 Memory 不会因为并发 CREATE 产生明显重复。

具体采用 PostgreSQL transaction-scoped advisory lock、candidate-key lock、唯一约束辅助或其他短锁机制，留实现阶段冻结；禁止在持锁期间等待 LLM。

---

# 35. Memory lifecycle

V2.2 最低状态：

```text
ACTIVE
SUPERSEDED
FORGOTTEN
```

只有 ACTIVE Memory 参与 Tiny Profile、memory.search 与 Model Context。

---

# 36. Memory Forget

用户“忘掉我喜欢晚上学习这件事”后：

```text
ACTIVE → FORGOTTEN
```

Forget 成功后立即：

- 不再进入 Tiny Profile；
- memory.search 不再返回；
- 不再参与 vector / lexical retrieval；
- 不再用于后续 context assembly。

Forget 不等于 Delete Thread。

## 36.1 Forget suppression

必须防止用户刚 Forget 后，旧 Background Formation Job 又从旧消息重新 CREATE 相同 Memory。

因此 MemoryManager 必须存在最小 internal suppression / tombstone 机制，用于阻止旧来源 / 旧 Job 自动复活已明确忘记的信息。

具体 fingerprint、source cutoff、保留期限留实现阶段。

---

# 37. Tiny Profile

少量高稳定 PROFILE 可以自动进入 Initial Context，因为这些偏好在大量未来对话中都有高复用价值，自动提供能避免新 Thread 像“失忆”。

允许自动加载的典型内容：默认语言、回复方式偏好、稳定技术偏好、长期工作习惯。

不应每次自动加载随机兴趣、多年前一次事件、低相关长期事实或大量用户档案。

Tiny Profile 必须严格受 ModelContextAssembler token budget 控制。架构只冻结“tiny、stable、small subset”，具体条数 / token 阈值通过 Eval 调整。

Memory MAY 有 `auto_context = true / false` 作为 context policy，不增加新 Memory Type。

---

# 38. Memory Retrieval

## 38.1 总体策略

```text
memory.search(query)
↓
user_id = current user
status = ACTIVE
↓
optional metadata filter
(type / related Thing)
↓
vector candidates
+
lexical candidates
↓
simple rank fusion
↓
canonical dedupe
↓
small Top-K
↓
Executive
```

## 38.2 Vector arm

pgvector 第一版优先使用 exact nearest-neighbor search。每用户 Memory 规模初期较小，exact search recall 完整；只有真实性能数据证明需要时，再增加 HNSW / IVFFlat。

## 38.3 Lexical arm

架构冻结“必须存在 lexical candidate arm”，但不在架构层锁死中文 tokenizer。

第一版优先评估 PostgreSQL 自身能力：Full Text Search、`pg_trgm`、项目名/比赛名 lexical exact/fuzzy query。

不得为此引入独立 Elasticsearch。

## 38.4 Fusion

V2.2 推荐 Reciprocal Rank Fusion（RRF），不引入 Cross Encoder reranker。

具体 candidate 数、RRF 参数、最终 Top-K 由 Memory Eval 调整；最终返回数量必须小，避免 Retrieval 自身污染上下文。

## 38.5 Recency

Recency 只能作为弱信号 / tie-breaker。不得将“更新”自动解释为“更真实”。稳定 PROFILE 可能很久以前形成但仍正确。

不建设不可解释的统一加权总分公式。

## 38.6 不增加 LLM importance score

V2.2 不保存 `importance = 0.87` 一类伪精确评分，除非未来真实 Eval 证明有明确收益。

---

# 39. Thing Resolution 与 Memory Retrieval 分离

```text
Thing Resolution
= 当前这个现实事务到底是哪一个

Memory Retrieval
= 过去长期留下了什么知识
```

用户“那个比赛现在怎么样？”应先 resolve Thing，再 `state.get_thing_context`，不能用 memory.search 猜当前状态。

用户“我以前比赛有没有犯过类似错误？”才是 memory.search 的典型场景。

---

# 40. State ↔ Memory Consistency

Memory 不能覆盖 State，不只靠 Prompt，而是四层工程保证。

## 40.1 Formation filtering

Formation 时读取 Current State，State-like candidate 不写 Memory。

## 40.2 MemoryManager reconciliation

Candidate commit 前重新读取最新 State。若 candidate 已被 Current State 修正或与 Current State 冲突，则 IGNORE / reconcile。

## 40.3 Runtime routing

如果用户问“现在是什么”，必须优先使用 authoritative State read。Memory 只能作为背景。

## 40.4 Context authority annotation

ModelContextAssembler 应明确区分：

```text
AUTHORITATIVE CURRENT STATE
NON-AUTHORITATIVE LONG-TERM MEMORY
```

不得把二者平铺成同等级文本。

---

# 41. Stale Memory repair

State mutation MAY 产生 `memory reconciliation hint`，后台 durable job 可以清理明显复制 Current State 的旧 Memory。

但必须保持：

```text
Runtime authority
= correctness

Background reconciliation
= data hygiene
```

即使 reconciliation Worker 暂时失败，系统仍必须依据 Current State 正确回答。

---

# 42. Memory Formation 并发

场景：Formation 开始时看到 Deadline = 19，用户随后改成 20，Formation LLM 最后返回 candidate 19。

MemoryManager commit 前必须重新读取 Latest State / version；发现 stale 后 IGNORE / reconcile。

禁止把数据库 transaction 从读取消息一路保持到 LLM 返回。

---

# 43. Thread lifecycle

## 43.1 Delete Thread

Delete Thread = 删除 Conversation。

流程：

```text
stop new Run
↓
cancel / settle active Run
↓
delete / clean Messages
↓
delete ThreadSummary
↓
clean thread-scoped checkpoints/runtime artifacts
↓
cancel pending thread Memory Formation
↓
orphan File evaluation
```

不得自动撤销 Thing、Task、ThingDate、Automation、已形成 Memory。

## 43.2 Deleted Message provenance

若 ThingDate provenance = Message M100，而 M100 后来被删除，ThingDate 不消失。

系统只表达 source status = DELETED / UNAVAILABLE。不得为 provenance 偷偷复制完整已删除 Message 原文。

---

# 44. File lifecycle

## 44.1 Delete File

用户主动 Delete File 表示不再保留该原始文件。

应删除：Object Storage original、extracted text、chunks、embeddings、preview / derived representation。

可保留最小 tombstone：file_id、status = DELETED、deleted_at、minimum metadata。

## 44.2 File deletion 不删除 derived fact

若 ThingDate = 20 日，provenance = File F1；后来 F1 删除，ThingDate 仍然是 20 日，只将 source 标记 unavailable。

Delete Evidence ≠ Undo Reality。

## 44.3 Delete File race

若 Agent 已读取 File，但在新的 State mutation COMMIT 前 File 已被用户删除，Application SHOULD 返回 `SOURCE_UNAVAILABLE`，不得继续从用户刚删除的 File 新形成事实。

如果 State mutation 已先 COMMIT，再删除 File，则事实继续存在。

## 44.4 Orphan 与 Delete 分离

```text
user Delete
≠ system orphan GC
```

只有没有任何 durable reference 的 File 才可以成为 orphan。

Durable reference 包括 Message/Thread、Thing、Personal State provenance、Evidence、Memory provenance、Automation context。

---

# 45. Thing deletion

普通产品操作优先：Complete、Cancel、Archive、Restore。

真正 Delete Thing 属于高影响动作，不应成为主要入口。

## 45.1 Thing-owned component

以下对象没有 Thing 就没有独立产品意义：ThingContextEntry、ThingDate、Blocker。Thing 真删除时可作为 owned component 清理。

## 45.2 Task

Task 可以 standalone，因此 Delete Thing ≠ Delete Task。默认可将 `task.thing_id → NULL`；具体是否同时 Cancel/Delete Task，应由高影响删除预览与用户意图决定。

## 45.3 File

Delete Thing 只移除 Thing ↔ File association，不能直接删除 File；之后真正 orphan 才 GC。

## 45.4 Memory

Delete Thing 不自动 Forget Memory。过去经验仍可能对未来有价值。

## 45.5 Automation

Thing 删除时 anchored relative Automation 必须 Cancel / Disable；强关联该 Thing 的其他 Automation 必须进入 delete dependency preview；不允许留下 dangling scheduler reference。

真正 Delete Thing SHOULD 进入 HITL。

---

# 46. Memory Forget 与 Conversation deletion 分离

```text
Forget Memory
≠ Delete Thread

Delete Thread
≠ Forget Memory
```

用户如要求“把有关这件事的记录和记忆都删除”，属于更广泛 privacy erase intent，不能偷换成普通 Delete Thread。

---

# 47. Account Delete

Account Delete 是全局数据生命周期，必须 durable、resumable、idempotent。

推荐：

```text
Delete Account request
↓
User.status = DELETING
COMMIT
↓
durable AccountDeletionJob
```

后台流程概念：

```text
block new Runs
settle / cancel active Runs
disable Automation
disable Devices / Push
cancel pending durable jobs
delete Threads / Messages
delete Personal State
delete Memory
delete eligible Files / Object Storage
clean runtime / checkpoint artifacts
delete/anonymize audit according privacy policy
revoke auth/session
↓
User.status = DELETED
```

不能试图在一个 HTTP request / 单一巨大数据库 transaction 中完成全部清理。

---

# 48. Attention

Attention 只冻结边界：

```text
Attention
= derived ranking / read model
```

输入可以来自 Thing、Task、ThingDate、Blocker、Automation、recent activity，用于 Today、Home、proactive hints、Automation-triggered Run。

Attention 不是 authoritative truth，不在本文继续设计独立权威表。

---

# 49. 最终逻辑数据模型

```text
User
│
├── Device
│
├── Thread
│   ├── Message
│   │   └── Attachment → File
│   └── ThreadSummary
│
├── Thing
│   ├── ThingContextEntry
│   ├── ThingDate
│   ├── Blocker
│   └── ThingFile → File
│
├── Task
│   └── thing_id?
│
├── Automation
│   ├── thing_id?
│   ├── task_id?
│   └── anchor_thing_date_id?
│
├── Memory
│   ├── related_thing_id?
│   ├── embedding
│   └── superseded_by_memory_id?
│
├── File
│
├── StateMutation
│
├── TimelineEvent
│
├── MemoryFormationJob
│
└── Runtime / Tool / other Durable Jobs
```

本文不定义最终 DDL。

---

# 49.1 核心实体逻辑字段与约束

本节只冻结**逻辑字段责任与约束方向**，不是最终 DDL。字段名可在 Repository / Migration 专项调整，但不得偷换语义。

## Thing

逻辑上至少需要承载：

```text
thing_id
user_id
name / title
status
archived
merged_into_thing_id?
version
created_at
updated_at
```

约束：

- owner-scoped；
- `status` 仅 ACTIVE / COMPLETED / CANCELLED；
- merge redirect 不能指向自身；
- `name/title` **不是唯一键**，不能用标题唯一性替代 Executive 的语义识别；
- merged Thing 不再作为 current candidate 返回。

## Task

逻辑上至少需要承载：

```text
task_id
user_id
thing_id?
title
status
scheduled time?
due time?
recurrence semantics?
version
created_at
updated_at
```

约束：

- `thing_id` nullable；
- status 仅 TODO / DONE / CANCELLED；
- Task title 不做全局唯一；
- recurrence 与 Automation schedule 不得复用同一个业务字段语义。

## ThingDate

逻辑上至少需要承载：

```text
thing_date_id
user_id
thing_id
type
label?
value
precision
certainty
timezone / local semantics when needed
version
primary provenance
created_at
updated_at
```

约束：

- MUST 属于 Thing；
- type 仅 DEADLINE / EVENT / MILESTONE；
- 不允许同一语义日期槽位长期存在多个互相冲突的 current truth；
- exact unique key（例如 type + semantic label）留 DDL 专项根据真实用例冻结，避免过早限制“报名截止 / 作品截止”等多个合法 Deadline。

## ThingContextEntry

逻辑上至少需要承载：

```text
entry_id
user_id
thing_id
label / semantic slot
content
version
primary provenance?
created_at
updated_at
```

约束：

- MUST 属于 Thing；
- Application SHOULD 更新同一 current semantic slot，而不是不断追加重复 entries；
- exact uniqueness 不在本文用 label 字符串硬编码。

## Blocker

逻辑上至少需要承载：

```text
blocker_id
user_id
thing_id
summary
status
version
primary provenance?
created_at
resolved_at?
updated_at
```

约束：

- MUST 属于 Thing；
- status 仅 OPEN / RESOLVED；
- resolved Blocker 默认退出 current blocker view，但保留历史语义。

## Memory

逻辑上至少需要承载：

```text
memory_id
user_id
type
content
status
version
auto_context?
related_thing_id?
superseded_by_memory_id?
embedding?
primary provenance / provenance refs
created_at
updated_at
```

约束：

- type 仅 PROFILE / SEMANTIC / EPISODIC；
- status 仅 ACTIVE / SUPERSEDED / FORGOTTEN；
- superseded_by 不得指向自身；
- 非 ACTIVE Memory 不参与正常 retrieval；
- embedding 不是 Memory authority，只是 retrieval representation；
- 不以 content 字符串唯一约束代替 MemoryManager consolidation。

## StateMutation

逻辑上至少需要承载：

```text
mutation_id
user_id
actor / channel
entity_type / entity_id
operation
before / after
version_before / version_after
provenance
run_id? / action_id?
created_at
```

约束：

- append-only / immutable audit semantics；
- 不成为 current state 的读取来源。

## TimelineEvent

逻辑上至少需要承载事件主体、关联 entity、用户可理解的事件语义、发生时间与必要 provenance。

约束：append-only；不是 SQL update log。

## MemoryFormationJob

逻辑上至少需要表达：

```text
job_id
user_id
source thread / range
status
not_before?
lease / retry metadata
created_at / updated_at
```

其 claim / lease / retry / recovery 直接继承 Backend V2.2 Durable Work 规范。

## ProvenanceRef / EvidenceRef

本文只冻结 typed reference 语义，不强制它们一定是独立表：

```text
kind
ref_id / URL
source status when resolvable
retrieved_at / locator only when evidence type needs it
```

删除来源后引用必须可表达 UNAVAILABLE / DELETED，而不是反向删除已经形成的现实。

---

# 50. 核心实体语义表

| Entity | 产品意义 | Current Truth | version | 历史策略 |
|---|---|---:|---:|---|
| Thing | 持续现实事务 | 是 | MUST | Mutation / Timeline / merge redirect |
| ThingContextEntry | Current Soft State | 是（低于 structured State） | MUST | Mutation / Timeline |
| Task | 用户未来行动 | 是 | MUST | Mutation / Timeline |
| ThingDate | 事务重要现实时间 | 是 | MUST | Mutation / Timeline |
| Blocker | 当前推进阻碍 | 是 | MUST | resolved + Timeline |
| Automation | 用户设置的未来系统行为 | 是 | MUST | Automation lifecycle |
| Memory | 跨 Thread 长期知识 | 非当前现实权威 | MUST | ACTIVE / SUPERSEDED / FORGOTTEN |
| Thread / Message | Conversation | 否 | 按需 | thread lifecycle |
| File | 原始资料 / Evidence | 否 | lifecycle version | tombstone / GC |
| StateMutation | Audit history | immutable history | 否 | immutable |
| TimelineEvent | User-meaningful history | immutable history | 否 | immutable |

---

# 51. Ownership

所有用户私有业务对象必须 owner-scoped 到稳定 internal `user_id`。

包括至少 Thread、Message、Thing、Task、ThingDate、Blocker、File、Memory、Automation、StateMutation、TimelineEvent、MemoryFormationJob。

Backend 不信任客户端声明 user_id / owner_id。

正确链：

```text
Business Session
↓
Auth Middleware
↓
AuthContext.internal_user_id
↓
Application / Repository ownership scope
```

---

# 52. PostgreSQL 数据设计原则

## 52.1 Authoritative State 不做万能 JSONB

可查询、可约束、涉及 invariant 的核心字段应使用明确关系/列语义，不得把所有业务现实塞入 `Thing.state_jsonb`。

## 52.2 JSONB 的合理使用

JSONB MAY 用于：StateMutation before/after、异构 Evidence metadata、Provider metadata、非权威且结构确实异构的 audit payload。

JSONB 不是逃避 Domain 设计的工具。

## 52.3 Referential Action

只有真正 parent-owned component 才考虑数据库 CASCADE。

独立业务对象之间优先 RESTRICT / NO ACTION、SET NULL 或 Application semantic deletion。

尤其不得因 FK 方便级联删除 Task、File、Memory、Automation。

---

# 53. pgvector / Retrieval 数据策略

- Memory embedding 存 PostgreSQL + pgvector；
- 先 user_id / ACTIVE metadata filter；
- 第一版优先 exact vector search；
- 真实性能数据证明需要后再考虑 HNSW / IVFFlat；
- lexical arm 依赖 PostgreSQL 本地能力；
- hybrid 使用简单 rank fusion；
- 不引入独立 Vector DB。

Embedding model、dimension、distance metric 属于实施阶段配置，不在本文冻结。

---

# 54. Application / Tool 边界

本文冻结语义，不冻结最终 Tool Set。

## 54.1 Read

Agent-facing read 继续优先聚合：

```text
state.get_overview
state.get_thing_context
memory.search
```

Thing Cards 只负责导航 / candidate recall，不是 authoritative state。

## 54.2 Write

Write Tool 必须绑定明确业务 Use Case。禁止 `state.update_everything`。

典型业务能力包括：create/update Thing、create/complete/cancel Task、set/correct ThingDate、update Current Soft State、create/resolve Blocker、create Task with Reminder、archive/restore Thing、merge Thing、remember/forget Memory。

最终命名、Schema、Policy 在 Tool 专项冻结。

---

# 55. Failure / Conflict Cases

以下场景 MUST 进入开发测试与 Agent Eval。

## Case F1 — Stale Memory vs Current State

```text
Memory: Deadline = 19
State:  Deadline = 20
```

用户问“什么时候截止？”必须返回 20。Memory 可进入后台 hygiene，但不能影响 current answer。

## Case F2 — Formation 与 State correction race

Formation 基于 19 号开始，用户同时改成 20 号。MemoryManager commit 前读取 Latest State：candidate stale → IGNORE / reconcile。

## Case F3 — UI / Agent version conflict

UI 把 Task 改为 DONE，Agent 仍基于 TODO old version。必须 VERSION_CONFLICT → reread → semantic re-evaluation，不能 silent overwrite。

## Case F4 — Commit 成功、Tool response 丢失

Thing 已创建，但进程在 response 前崩溃。恢复后同 action_id 返回 original persisted receipt，不能重复创建。

## Case F5 — Partial multi-effect failure

一句话形成 Thing / Date / Task / Automation，其中 Task 失败。Assistant 必须准确报告部分成功，不得说全部成功，也不得把成功效果当成失败 rollback。

## Case F6 — Relative Automation stale trigger

Deadline 已修改，但 Scheduler 持有旧 occurrence。执行前验证最新 anchor/version：旧 occurrence → SKIP / RESCHEDULE。

## Case F7 — Delete Thread while Worker running

Delete Thread 必须先收敛 active Run，并取消 pending thread Memory Formation。不能用户删除聊天后 Worker 又从该 Thread 新建 Task / Memory。

## Case F8 — Delete File 与 State Formation race

File 在 State mutation commit 前已删除：SOURCE_UNAVAILABLE。不能继续根据已删除 File 新形成事实。

## Case F9 — Forget Memory 与 old Formation Job race

用户 Forget M1 后，旧 Job 又提取同一偏好。MemoryManager suppression 必须阻止旧信息立即复活。

## Case F10 — Thing Merge dangling references

Thing B merged into A 后，current Task / Automation 等引用必须收敛；旧 B 保留 redirect；旧 Message / provenance 仍可解析。

## Case F11 — Delete Thing with relative Automation

删除 Thing 导致 anchor ThingDate 消失时，relative Automation 必须 cancel / disable，不得留下 dangling scheduler。

## Case F12 — Redis outage

Redis 故障时 Personal State、Memory、MemoryFormationJob、Automation truth 不丢；Worker 能 PostgreSQL fallback polling。

---

# 56. User Journey Acceptance

Backend Freeze 前至少验证以下真实自然语言路径。

### 持续事项

> “我要准备软件杯。”

→ 正确形成 Thing。

### Current Soft State

> “老师现在最关心 Demo。”

→ ThingContextEntry，而不是错误 Task / Memory。

### Standalone Task

> “今天得取快递。”

→ standalone Task。

### Task + Reminder

> “下午三点提醒我取快递。”

→ Task + Automation。

### Current Agent Action

> “帮我查一下官网。”

→ 立即 Tool Action，不创建 Task。

### Periodic Task

> “我每周日都要写周报。”

→ recurring Task capability。

### Condition Automation

> “官网公布名单以后告诉我。”

→ Automation only。

### Correction

> “我刚才说错了，是 20 号。”

→ current ThingDate correction，不保留两个 current truth。

### Blocker

> “老师还没给数据，所以实验现在没法做。”

→ OPEN Blocker。

### Resolve Blocker

> “老师把数据给我了。”

→ RESOLVED。

### Explicit Remember

> “记住我喜欢晚上集中学习。”

→ PROFILE Memory。

### Retention intent routing

> “记住，比赛截止改成 20 号。”

→ State correction，不复制 Deadline Memory。

### New Thread

新 Thread history 可以为空，但仍能通过 Tiny Profile、Thing Cards、State tools、memory.search、file.search / inspect 保持长期连续性。

---

# 57. Frozen Decisions

以下为 Personal State & Memory v2.2 正式冻结结论。

1. Personal State 是 authoritative domain，不是一张万能大表。
2. HarmonyOS 通过 Personal State Overview 聚合展示“老实人现在如何理解我”。
3. Thing 只表示持续现实事务。
4. Thing lifecycle 仅 ACTIVE / COMPLETED / CANCELLED。
5. Archive 是关注 / 展示属性，不是业务 lifecycle。
6. Duplicate Thing 通过 Executive 判断 + canonical merge，不靠 vector threshold 自动合并。
7. Task 是一等对象，`thing_id` nullable。
8. Task lifecycle 仅 TODO / DONE / CANCELLED。
9. V2.2 产品能力支持 recurring Task，但不与 recurring Automation 混淆。
10. Task Time、ThingDate、Automation Trigger 严格分离。
11. 用户未来行动与系统未来行动分离；“提醒我取快递”默认 Task + Automation。
12. 同一个不可拆 Task+Reminder intent 使用 Application transaction。
13. ThingDate type 仅 DEADLINE / EVENT / MILESTONE。
14. ThingDate 保留 precision、certainty、timezone/local semantics、provenance。
15. ThingDate correction 采用稳定 ID + current update + version；旧值进入历史。
16. `supplemental_context` 收敛为 ThingContextEntry small current entries，不允许无限 append blob。
17. Blocker 保留为 Thing-level 一等对象，仅 OPEN / RESOLVED。
18. V2.2 不建设 Generic Relation Graph。
19. Candidate Durable Effects 属于 Run execution，不新增 CandidateEffect domain table。
20. 只有 Application COMMIT 后才形成 Current State。
21. 同一 User Turn 可以产生多个 durable effect，并允许真实 partial success。
22. 同一个业务 invariant 必须在一个 Application transaction 内保证完整性。
23. Final Response 必须以 persisted receipts 为依据。
24. Correction 必须修改 current truth，不能叠加多个 current fact。
25. StateMutation = 系统级业务 mutation audit；Timeline = 用户有意义历史。
26. Provenance 与 Evidence 分离；V2.2 优先轻量 primary provenance / evidence。
27. 所有重要 mutable state 使用 version / expected_version。
28. VERSION_CONFLICT 后重读现实并重新语义判断，禁止 blind stale retry。
29. 默认 PostgreSQL Read Committed + optimistic concurrency。
30. 禁止持 DB transaction / row lock 等待 LLM 或 HITL。
31. Relative Automation 执行前必须重新验证最新 ThingDate anchor。
32. mutation action_id / idempotency 必须支持 crash 后 replay original receipt。
33. Memory 仅 PROFILE / SEMANTIC / EPISODIC。
34. Current Personal State 不复制成长 Memory。
35. “记住”是 retention intent，不是直接存储路由。
36. Explicit Remember 走 foreground MemoryManager。
37. Background Formation 使用 PostgreSQL durable job，不每轮额外调用 Memory LLM。
38. Formation = Selection + Distillation；MemoryManager = reconciliation。
39. 所有 Memory write 必须经过唯一 MemoryManager boundary。
40. MemoryManager 收敛为 CREATE / REVISE / CONSOLIDATE / IGNORE；FORGET 是用户动作。
41. Memory lifecycle 仅 ACTIVE / SUPERSEDED / FORGOTTEN。
42. Tiny Profile 只自动加载极少数稳定 PROFILE，并受 Context Budget 限制。
43. Memory Retrieval = metadata filter + vector + lexical + simple rank fusion + small Top-K。
44. 第一版 pgvector 优先 exact search；HNSW/IVFFlat 后置到真实性能证据出现。
45. V2.2 不使用 cross-encoder reranker，不建设通用 RAG 平台。
46. Thing Resolution 与 Memory Retrieval 是两个不同问题。
47. Runtime authority 保证 State > Memory；后台 reconciliation 只负责 hygiene。
48. Delete Thread 只删除 Conversation，不撤销已形成现实。
49. Delete File 不自动删除由该 File 已形成的事实。
50. Forget Memory 不等于 Delete Conversation。
51. 普通 Thing 生命周期优先 Complete / Cancel / Archive；真正 Delete Thing 为高影响操作。
52. Account Delete 使用 durable resumable lifecycle job。
53. Attention 仅为 derived read model，不成为 authoritative truth。
54. PostgreSQL + pgvector 保持 authoritative persistence / retrieval 基础。
55. Redis 只作为 non-authoritative cache / coordination / wake-up。

---

# 58. Deferred Details

以下内容明确推迟到后续实施专项，不在本文提前冻结。

## 58.1 Tool / Contract

- 最终 Agent Tool 名称；
- Tool input/output JSON Schema；
- REST path；
- SSE `state.changed` schema；
- Error code 最终枚举；
- HITL 每个 Use Case 的具体策略。

## 58.2 Database DDL

- 最终表名；
- 列类型；
- index 名称；
- migration；
- partial unique index；
- exact FK `ON DELETE` 动作；
- audit retention DDL。

## 58.3 Recurring Task

- recurrence spec；
- template / occurrence 是否拆分；
- missed occurrence 语义；
- fixed schedule vs after-completion；
- 完成历史模型。

## 58.4 Memory

- embedding provider / model / dimension；
- lexical tokenizer 最终选择；
- pg_trgm / PostgreSQL FTS 实测取舍；
- RRF 参数；
- candidate size / Top-K；
- Tiny Profile token budget；
- Formation idle window；
- catch-up N；
- forget suppression 的具体 fingerprint / retention；
- MemoryManager reconciliation lock 实现。

## 58.5 Evidence

- WebEvidence 是否独立表；
- multi-evidence 何时升级；
- evidence locator；
- deleted-source tombstone 最终字段。

## 58.6 Delete / Privacy

- Delete Thing dependency preview UX；
- audit retention；
- account deletion 法规 / privacy retention；
- Object Storage delete retry；
- external provider resource cleanup。

## 58.7 Attention

- ranking algorithm；
- Today / Home score；
- proactive threshold。

---

# 59. 官方与成熟产品设计依据

以下资料用于校准设计原则，**不代表老实人机械照搬其具体数据模型**。

## 59.1 LangGraph / LangChain

### Memory conceptual guide

LangGraph 官方明确区分 thread-scoped short-term memory 与 cross-thread long-term memory，并指出长期 Memory 可在 hot path 更新，也可后台形成。

- https://docs.langchain.com/oss/python/concepts/memory

### LangGraph Persistence

Checkpoint 保存 thread runtime state；Store 用于跨 thread 持久数据。老实人据此保持 LangGraph Checkpoint ≠ Long-term Memory authority。

- https://docs.langchain.com/oss/python/langgraph/persistence

### LangGraph Interrupts

官方明确指出 interrupt resume 会重新执行节点，因此 interrupt 前副作用应幂等。

- https://docs.langchain.com/oss/python/langgraph/interrupts

### Long-term Memory / Store

LangGraph 官方提供 Postgres-backed Store 能力，但这是框架能力，不要求产品必须把 Store 作为业务 Memory authority。

- https://docs.langchain.com/oss/python/langchain/long-term-memory

## 59.2 PostgreSQL

### Transaction Isolation / MVCC

PostgreSQL 默认 Read Committed；Serializable 提供更强保证，但应用必须处理 serialization failure 并重试完整事务。老实人据此采用 Read Committed + expected_version 作为默认策略，只在少量强 invariant 中提高隔离级别。

- https://www.postgresql.org/docs/current/transaction-iso.html
- https://www.postgresql.org/docs/current/mvcc.html

### Explicit Locking

PostgreSQL 文档提醒长时间持有 transaction / lock 会造成等待与死锁风险，不应等待用户输入。

- https://www.postgresql.org/docs/current/explicit-locking.html

### Foreign Key Referential Actions

PostgreSQL 支持 NO ACTION / RESTRICT / CASCADE / SET NULL 等 referential actions。老实人只对真正 parent-owned component 使用自动级联；独立业务对象删除由 Application 语义决定。

- https://www.postgresql.org/docs/current/sql-createtable.html
- https://www.postgresql.org/docs/18/ddl-constraints.html

### JSONB

PostgreSQL JSONB 适合异构 document / metadata，并支持 GIN 等索引。老实人只在 audit / metadata 等合理场景使用，不把整个 authoritative domain 塞进 JSONB。

- https://www.postgresql.org/docs/current/datatype-json.html

## 59.3 pgvector

pgvector 官方说明默认 exact nearest-neighbor search 提供完整 recall，HNSW / IVFFlat 为 approximate search，并支持与 PostgreSQL text search 组合做 Hybrid Search及用 Reciprocal Rank Fusion 合并结果。

老实人 V2.2 因此优先：

```text
exact vector
+
lexical arm
+
simple RRF
```

真实性能需求出现前不提前上 approximate index。

- https://github.com/pgvector/pgvector

## 59.4 OpenAI Memory 产品经验

OpenAI Memory 产品提供自动形成长期记忆、用户查看 / 修改 / 删除，以及 Memory 与聊天历史不同生命周期的产品控制。

老实人借鉴的是“用户可控、可纠正、可忘记”的原则，不复制其内部实现。

- https://help.openai.com/en/articles/8590148

## 59.5 Mature Product References

### Things

Things 将 repeating to-do、reminder 与 deadline 分开表达，周期 to-do 是一等用户能力。老实人借鉴其“任务行为与提醒时间分离”的产品心智。

- https://culturedcode.com/things/support/articles/2803564/
- https://culturedcode.com/things/support/articles/3743733/

### Todoist

Todoist 明确区分 recurring task 与 reminder，进一步支持 Task recurrence ≠ Reminder recurrence。

- https://www.todoist.com/help/articles/introduction-to-recurring-dates-YUYVJJAV
- https://www.todoist.com/help/articles/introduction-to-reminders-9PezfU

### Linear

Linear 的 blocker / duplicate / relation 设计说明“阻碍”和“重复”在某些产品中确实有独立业务价值。老实人只保留最小 Blocker 与 canonical merge，不复制其完整 relation system。

- https://linear.app/docs/issue-relations

---

# 60. 一句话定义

> **老实人 Personal State & Memory v2.2 是一套以 PostgreSQL 保存用户“当前现实”的 authoritative Personal State、以 pgvector + lexical hybrid retrieval 支持跨 Thread Long-term Memory，并通过语义化 Application mutation、version / expected_version、durable receipts、Correction / Audit、轻量 provenance、Memory Formation / consolidation 与明确生命周期规则，保证个人 Agent 在新 Thread、并发修改、崩溃恢复、文件删除和长期使用情况下仍然保持当前真相唯一、历史可追溯、长期记忆可控且不会越用越脏的正式后端设计。**

---

# 61. 后续专项衔接

本文冻结后，下一步可以进入：

1. **Personal State / Memory Tool 技术设计**：冻结 Agent-facing read/write capability、Schema、error semantics、policy、HITL。
2. **Application Use Case 与 Repository 设计**：冻结事务边界、expected_version、Mutation Receipt、derived effects。
3. **PostgreSQL 逻辑模型 → 最终 DDL / Migration**：将本文逻辑实体映射为表、约束、索引与 migration。
4. **Memory Eval / State Eval**：使用真实自然语言 User Journey 验证 Formation、Correction、Retrieval、State > Memory、重复控制与长期数据卫生。
5. **Personal State Contract / HarmonyOS Read Model**：冻结 `state.get_overview`、`state.get_thing_context` 与客户端 Personal State Overview 所需 Contract。
