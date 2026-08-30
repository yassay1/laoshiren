# 老实人 Automation / Scheduler / Notification 技术设计 v2.2

> **文档状态：正式开发专项基线（Baseline）**  
> **版本：v2.2**  
> **适用范围：老实人 Backend V2.2**  
> **目标平台：HarmonyOS App + Single Executive Agent**  
> **权威持久化：PostgreSQL**  
> **Redis：non-authoritative wake-up / coordination only**  
> **Push Provider：Huawei Push Kit**  
> **本文不包含：最终 SQL DDL、最终 OpenAPI、具体 Push 配额、最终 Scheduler interval、最终默认 Condition cadence/expiry 参数**

---

# 0. 文档目的

本文正式冻结老实人 Backend V2.2 的以下专项能力：

- Automation Domain；
- ONCE / RECURRING / RELATIVE / CONDITION；
- Time / Timezone / DST；
- Relative ThingDate Binding；
- `next_trigger_at`；
- Scheduler Scanner；
- Occurrence；
- DurableJob；
- Misfire；
- Crash / Recovery；
- CONDITION Watch；
- Bounded Agent Run；
- Condition Budget；
- NotificationIntent；
- NotificationDelivery；
- Huawei Push；
- Multi-device；
- Push Token Lifecycle；
- Task / Thing / ThingDate 与 Automation 联动；
- Account Delete；
- Failure Matrix；
- V1 → V2.2 Migration；
- Frozen Decisions / Deferred Details。

本文的核心问题：

> **用户说“明天提醒我”“每周提醒我”“截止日前一天提醒我”“官网出结果以后告诉我”以后，系统怎样把这些未来意图可靠持久化；怎样在正确时间产生一次逻辑执行；怎样避免服务器重启、Redis 故障、多实例并发、Push timeout、Token 失效造成提醒丢失或明显重复；又怎样保证后台 Condition Watch 不无限运行、不无限搜索、不无限烧钱。**

---

# 1. 上位架构约束

本文继承：

1. 《老实人_Backend_V2_总体架构设计_v2.2_正式基线版》
2. 《老实人_Agent_Runtime技术设计_v2.2》
3. 《老实人_最小用户与通知支持技术设计_v2.2》
4. 《老实人_Personal_State与Memory技术设计_v2.2》
5. 《老实人_Tool_API_Policy技术设计_v2.2》
6. 《老实人_File_Multimodal_Search_Evidence技术设计_v2.2》

以下原则不得被本专项推翻：

```text
Single Executive

Task
= 用户未来要做什么

ThingDate
= 现实中存在什么日期事实

Automation
= 系统未来应该做什么

Run
= 一次 Agent execution lifecycle

DurableJob
= 谁负责执行某项 infrastructure work

Personal State
= 当前现实 authority

PostgreSQL
= durable truth

Redis
= wake-up / coordination only

LLM
= semantic decision
≠ authorization
≠ scheduler truth
≠ external delivery truth
```

---

# 2. V2.2 明确不做

本专项不引入：

- Temporal；
- Kafka；
- Quartz Cluster；
- Celery Beat 作为新 durable truth；
- Redis Sorted Set 作为唯一 schedule authority；
- 长时间 LangGraph sleep；
- 长时间 Worker lease；
- 完整 RFC5545 Calendar Platform；
- 完整 Cron DSL 作为业务 authority；
- 无限 Condition Watch；
- Condition DSL / Rules Engine；
- adaptive polling；
- Continuous subscription/change-stream；
- Notification Provider exactly-once 声明；
- NotificationOutbox 独立第五张表；
- NotificationAttempt 独立表；
- ConditionEvaluation 独立表；
- Scheduler Leader Election；
- 多套 Timer/Trigger/Job 同义对象；
- Push Provider 状态作为 Automation 状态；
- Provider Push Token 写进 Automation；
- Task/Thing Archive 自动取消 Reminder；
- Task Reopen / Thing Reactivate 自动复活旧 Automation。

---

# 3. 核心概念边界

```text
Automation
= 未来意图定义

Occurrence
= 一次逻辑触发

DurableJob
= 执行工作项

Run
= 一次 Agent 执行

NotificationIntent
= 一次用户级通知事件

NotificationDelivery
= 向一个具体 Endpoint 的外部送达

Push Provider
= 外部传输通道
```

因此：

```text
Automation
≠ Occurrence
≠ DurableJob
≠ Run
≠ Notification
≠ Push Delivery
```

---

# 4. Automation 正式定义

> **Automation = 用户授权老实人在未来某个时间或某个条件下执行某项系统行为的 durable intention。**

关键词：

```text
user-authorized
future
system action
durable intention
```

Automation 不是 Timer，也不是 Job。

---

# 5. Automation 与 Task / ThingDate

```text
Task
= 用户未来的行动

ThingDate
= 当前现实中的日期事实

Automation
= 系统未来的行动
```

例如：

```text
“明天交材料”
→ Task

“报名截止9月19日”
→ ThingDate

“9月18日提醒我”
→ Automation
```

三者可以关联，但不能合并。

---

# 6. Standalone Automation

Automation 可以：

```text
Standalone
```

例如：

> “明天9点提醒我交水费。”

不需要制造一个 Thing。

---

# 7. Linked Automation

Automation MAY 关联：

```text
Thing
Task
ThingDate
```

不同关联语义：

```text
linked_task_id
→ lifecycle dependency

linked_thing_id
→ matter-level context/lifecycle

anchor_thing_date_id
→ RELATIVE schedule authority
```

---

# 8. 四种 Automation Type

V2.2 只保留：

```text
ONCE
RECURRING
RELATIVE
CONDITION
```

不增加：

```text
CRON
DELAY
WATCH
EVENT
INTERVAL
CALENDAR
```

这些只是实现形式或产品命名。

---

# 9. 四种类型的 schedule authority

| 类型 | Authority |
|---|---|
| ONCE | 一个确定 absolute instant |
| RECURRING | local recurrence rule + IANA timezone |
| RELATIVE | stable ThingDate anchor + relative rule |
| CONDITION | condition/evaluation plan |

统一拥有：

```text
next_trigger_at
```

但除 ONCE 外：

> **`next_trigger_at` 只是 materialized scheduling index，不是 schedule authority。**

---

# 10. ONCE

示例：

> “明天下午3点提醒我交材料。”

创建时：

```text
Device timezone
↓
Executive理解
↓
normalized local datetime
↓
UTC instant
```

Authority：

```text
trigger_at = absolute UTC instant
```

另外保存：

```text
timezone_at_creation
original_expression
```

用于解释。

---

# 11. ONCE 不随旅行自动移动

上海创建：

```text
明天下午3点
```

若创建时解释为：

```text
2026-08-31 15:00 Asia/Shanghai
= 07:00 UTC
```

用户第二天到了东京：

仍在：

```text
07:00 UTC
```

触发。

若用户希望：

> “改成日本时间下午3点。”

必须明确 Reschedule。

---

# 12. RECURRING

示例：

> “每周一晚上8点提醒我写周报。”

Authority 不能只是：

```text
next_trigger_at
```

必须保留：

```text
local recurrence semantics
+
IANA timezone
```

---

# 13. Recurrence Strategy

V2.2 采用：

> **RRULE-inspired Simple Recurrence**

而不是：

```text
Cron authority
```

也不是：

```text
完整RFC5545实现
```

---

# 14. V2.2 Recurrence Subset

支持：

```text
frequency:
  DAILY
  WEEKLY
  MONTHLY

interval >= 1

weekdays?

day_of_month?

local_time

start_local

end:
  forever
  until
  count
```

---

# 15. 暂不支持

```text
SECONDLY
MINUTELY
HOURLY
YEARLY

BYSETPOS
BYYEARDAY
BYWEEKNO

EXDATE
RDATE

法定节假日规则

每月最后一个工作日

第N个周二
```

---

# 16. “工作日”

V2.2：

```text
工作日
= Monday-Friday
```

不等于：

> 国家法定工作日 + 调休。

---

# 17. MONTHLY 不存在日期

例如：

> “每月31号提醒。”

2月没有31号。

V2.2：

```text
skip该occurrence
```

不偷偷改成：

```text
28号
```

“月底”是另一种语义，Deferred。

---

# 18. Timezone Authority

四个概念必须分离：

```text
Device timezone
User timezone
Automation timezone
Server timezone
```

---

# 19. Device Timezone

作用：

> 创建/修改 Automation 时理解用户自然语言。

例如：

```text
Asia/Shanghai
```

解释：

> “明天晚上8点。”

它不是已创建 Automation 的长期 authority。

---

# 20. User Timezone

MAY 作为：

```text
Device timezone unavailable
```

时的 fallback。

已有 Automation 不因 User timezone 后来改变而自动重解释。

---

# 21. Automation Timezone

Automation 一旦创建：

> **自身保存的 IANA timezone 是未来调度 authority。**

例如：

```text
Asia/Shanghai
America/New_York
```

不能只保存：

```text
UTC+8
UTC-5
```

---

# 22. Server Timezone

业务语义上：

```text
irrelevant
```

Backend 可统一运行 UTC。

服务器部署地不能改变 Reminder 时间。

---

# 23. 旅行语义

上海创建：

> “每天晚上8点提醒。”

```text
timezone = Asia/Shanghai
local_time = 20:00
```

后来人在东京：

东京当地：

```text
21:00
```

收到。

V2.2 不做：

```text
floating local schedule
```

---

# 24. Floating Schedule Deferred

“无论我在哪，都按当地晚上8点提醒”需要：

- 当前设备 timezone；
- 多设备冲突；
- 旅行判断；
- 用户当前地域 authority。

V2.2 不实现。

---

# 25. DST

Recurring 每次必须：

```text
calculate next local recurrence
↓
apply IANA timezone rules
↓
derive UTC instant
```

禁止：

```text
previous UTC + 24h
```

---

# 26. DST 不存在的 local time

例如：

```text
America/New_York
02:30
```

春季 DST 当天不存在。

V2.2：

```text
skip该occurrence
```

不自动变 03:00。

---

# 27. original_expression

Automation SHOULD 保存：

```text
original_expression
```

例如：

```text
“截止日前一天晚上提醒我”
```

用途：

- UI解释；
- Debug；
- Migration；
- 时间语义追踪。

但：

```text
normalized schedule
= authority

original_expression
= explainability only
```

---

# 28. Scheduler 禁止重新调用 LLM 解析 original_expression

一旦创建：

```text
raw expression
```

不得每次 Scheduler 都重新理解。

否则 Model/Prompt变化会导致 schedule 漂移。

---

# 29. RELATIVE

示例：

> “软件杯截止日前一天晚上7点提醒我。”

如果：

```text
ThingDate D1
deadline = 9月19日
```

Automation 必须保存：

```text
anchor_thing_date_id = D1
+
RelativeRule
```

不能只保存：

```text
9月18日19:00
```

---

# 30. Relative Binding

`anchor_thing_date_id` MUST 是结构化 relation。

不能埋进 opaque JSON。

原因：

```text
ThingDate correction
↓
快速找到所有linked RELATIVE Automation
```

---

# 31. Calendar Offset 与 Duration Offset

不能把：

```text
“前一天”
```

统一压成：

```text
-86400 seconds
```

必须区分：

```text
CALENDAR offset
DURATION offset
```

---

# 32. RelativeRule 逻辑示例

“截止日前一天晚上7点”：

```text
anchor = D1
calendar_days = -1
local_time = 19:00
timezone = Asia/Shanghai
```

“截止前2小时”：

```text
anchor = D1
duration_hours = -2
```

---

# 33. ThingDate Precision

如果：

```text
ThingDate
precision = DATE
value = 2026-09-19
```

用户：

> “提前2小时提醒。”

不够确定。

Backend 不能擅自把 DATE 当：

```text
00:00
```

必须返回：

```text
DOMAIN_CONFLICT / clarification required
```

---

# 34. Relative Correction Invariant

初始：

```text
ThingDate D1
19日

Automation A1
anchor=D1
-1 calendar day
19:00

next=18日19:00
```

用户纠正：

```text
D1
19 → 20
```

必须：

```text
A1
next
18 → 19
```

---

# 35. Relative Correction Transaction

在当前 modular monolith / PostgreSQL 架构下：

```text
ThingDate correction
+
linked RELATIVE recomputation
+
definition_revision bump
```

SHOULD 在同一个 Application transaction 中完成。

不引入 Kafka / eventual consistency。

---

# 36. Anchor Delete

ThingDate 真正删除：

```text
linked RELATIVE Automation
→ CANCELLED

cancel_reason = ANCHOR_REMOVED
```

不增加：

```text
INVALID
NEEDS_ATTENTION
```

状态。

---

# 37. Absolute 与 Relative 独立

如果：

```text
ONCE
18号19:00
```

和：

```text
RELATIVE
deadline -1 day
```

当前碰巧时间相同。

Deadline correction 后：

```text
ONCE
不变

RELATIVE
跟随
```

---

# 38. Automation Core

逻辑模型：

```text
automation_id
owner_user_id

type:
  ONCE
  RECURRING
  RELATIVE
  CONDITION

status:
  ACTIVE
  COMPLETED
  CANCELLED

intent

linked_thing_id?
linked_task_id?

timezone?

next_trigger_at?

original_expression?

execution_scope

version
definition_revision

created_at
updated_at

completion_reason?
cancel_reason?
```

---

# 39. Automation Status

正式保持：

```text
ACTIVE
COMPLETED
CANCELLED
```

不增加：

```text
FAILED
PAUSED
```

---

# 40. 为什么没有 FAILED

Automation 是：

> future intention definition。

某次执行失败属于：

```text
Occurrence
DurableJob
NotificationDelivery
```

而不是 Definition failure。

Recurring 某一次失败：

> 下一次仍应继续。

---

# 41. 为什么没有 PAUSED

Pause/Resume 会增加：

- Pause Tool；
- Resume Tool；
- UI；
- Misfire semantics；
- next trigger recomputation。

V2.2 Deferred。

---

# 42. Reschedule

同一用户意图的时间修改：

```text
update original Automation
version++
definition_revision++
```

不：

```text
cancel old
create new
```

---

# 43. Historical Occurrence 不重写

修改 schedule 后：

```text
过去 Occurrence
```

保持原 scheduled_for。

只影响未来。

---

# 44. version 与 definition_revision

```text
version
= whole object optimistic concurrency

definition_revision
= future execution semantic generation
```

例如：

```text
改display label
→ version++

改时间
→ version++
→ definition_revision++

改Condition criterion
→ version++
→ definition_revision++
```

---

# 45. next_trigger_at

正式定义：

> **统一供 Scheduler 扫描的 materialized UTC index。**

适用于：

```text
ONCE
RECURRING
RELATIVE
CONDITION
```

除 ONCE 外：

```text
next_trigger_at
≠ authority
```

可从 authoritative spec 重算。

---

# 46. Durable Scheduling Architecture

正式采用：

```text
PostgreSQL Automation
↓
next_trigger_at
↓
Scheduler Scanner
↓
Occurrence
↓
DurableJob
↓
Redis wake-up
↓
Worker
```

---

# 47. Scheduler Role

Scheduler 只负责：

```text
发现due Automation
materialize logical Occurrence
enqueue DurableJob
advance next_trigger
```

禁止：

```text
LLM
Search
Push
HTTP external call
sleep
等待用户
```

---

# 48. PostgreSQL 是 Scheduler Truth

以下都在 PostgreSQL：

```text
Automation
Occurrence
DurableJob
```

Redis：

```text
wake-up only
```

不保存唯一 future schedule truth。

---

# 49. Active-active Scheduler

允许：

```text
S1
S2
S3
```

多个 Scheduler 同时扫描。

不需要 Leader Election。

---

# 50. Due Scan

逻辑：

```sql
WHERE status = ACTIVE
  AND next_trigger_at <= database_now
FOR UPDATE SKIP LOCKED
```

`SKIP LOCKED` 只用于：

```text
queue-like claim
```

不能成为普通 Personal State 一致性读取方式。

---

# 51. Occurrence

正式定义：

> **某一条 Automation 在一个确定 logical schedule slot 上产生的一次 durable trigger instance。**

---

# 52. 为什么 Occurrence 必须存在

它回答：

```text
这次提醒本来什么时候发生？
是否触发？
是否失败？
是否被取消？
```

而不是依赖 Job log 猜。

---

# 53. Occurrence Logical Model

```text
occurrence_id
automation_id

definition_revision

scheduled_for
materialized_at

status

durable_job_id?

evaluation_receipt?

created_at
settled_at?
```

---

# 54. Occurrence Uniqueness

冻结：

```text
(automation_id, definition_revision, scheduled_for)
```

或等价唯一约束。

作用：

> 同一 definition generation、同一 logical slot 只能有一个 Occurrence。

---

# 55. Occurrence + Job Duplicate Protection

三层：

```text
Row Lock
→ 正常并发分工

Occurrence UNIQUE
→ logical duplicate correctness

DurableJob dedupe
→ 一个Occurrence只有一个execution work item
```

---

# 56. DurableJob Dedupe

建议逻辑：

```text
AUTOMATION_OCCURRENCE:{occurrence_id}
```

或等价唯一键。

---

# 57. Atomic Materialization

Scheduler 一次 materialization：

```text
BEGIN

lock due Automation

revalidate

derive logical slot

INSERT Occurrence

INSERT DurableJob

advance Automation.next_trigger_at

if schedule exhausted:
    update lifecycle as appropriate

COMMIT

best-effort Redis wake-up
```

---

# 58. 为什么必须同事务

防止：

```text
Occurrence有，Job没有

Job有，next_trigger没推进

next_trigger推进，但当前Occurrence没创建
```

任何中间 crash 都应该：

```text
rollback全部
```

---

# 59. Redis Failure

DB COMMIT 后 Redis publish 失败：

```text
Occurrence durable
DurableJob durable
```

Worker fallback polling 仍可执行。

所以：

```text
Redis down
≠ Reminder lost
```

---

# 60. Lazy Occurrence Materialization

不提前生成：

```text
未来一年365条Occurrence
```

只在 due 时逐个/小批生成。

---

# 61. ONCE / RELATIVE one-shot materialize

成功创建 Occurrence 后：

```text
next_trigger_at = NULL
```

避免重复 due scan。

Automation 在 Occurrence settle 后再：

```text
COMPLETED
```

---

# 62. RECURRING Advance

每次：

```text
authoritative RecurrenceSpec
+
IANA timezone
↓
next valid local slot
↓
UTC
↓
next_trigger_at
```

禁止：

```text
previous UTC + fixed seconds
```

---

# 63. Scheduler Clock

due comparison SHOULD 使用：

```text
database time
```

作为多实例统一时间参考。

---

# 64. Scheduler Precision

不承诺：

```text
20:00:00.000
```

精确触发。

提供：

```text
bounded scheduling lag
```

具体 scanner interval/p95 target Deferred。

---

# 65. Batch

首版：

```text
single row
或
small bounded batch
```

短事务优先。

不预建大规模 Scheduler throughput。

---

# 66. Isolation

默认：

```text
READ COMMITTED
+
row lock
+
unique constraints
```

不默认 SERIALIZABLE。

---

# 67. Deadlock

采用：

```text
short transaction
consistent lock order
whole transaction retry
```

---

# 68. Misfire

定义：

> logical scheduled time 已经过，但系统没有在正常窗口 materialize/execute。

V2.2 只保留：

```text
FIRE_ONCE
SKIP
```

---

# 69. FIRE_ONCE

含义：

> 从 downtime 中最多恢复一个当前仍有意义的用户动作。

不是：

> 把所有 missed slot 全部补一遍。

---

# 70. ONCE Misfire

默认：

```text
FIRE_ONCE
```

但受：

```text
max lateness / stale horizon
```

约束。

过旧：

```text
SKIP
```

具体时间 Deferred。

---

# 71. RECURRING Misfire

停机多天：

```text
不补所有missed occurrence
```

最多：

```text
补一个最新且仍有意义的recovery occurrence
```

然后推进到 future slot。

---

# 72. CONDITION Misfire

历史 check 不 backfill。

恢复后：

```text
最多做一次current check
```

因为用户关心的是：

> 现在条件是否成立。

---

# 73. Occurrence Status

正式：

```text
MATERIALIZED
SUCCEEDED
NOT_MET
FAILED
CANCELLED
SKIPPED
```

---

# 74. 为什么没有 RUNNING

DurableJob 已经有：

```text
READY
CLAIMED/RUNNING
retry
lease
```

Occurrence 只表达：

> logical trigger outcome。

---

# 75. Occurrence FAILED

一次执行最终失败：

```text
Occurrence → FAILED
```

Automation 不因此 FAILED。

Recurring/Condition 可继续未来触发。

---

# 76. Occurrence CANCELLED

表示：

> 已 materialize，但在完成之前因为 Definition/Lifecycle 变化失效。

例如：

```text
Automation cancel
Reschedule
ThingDate correction
Task complete
Account Delete
```

---

# 77. Occurrence SKIPPED

表示：

> slot存在，但根据调度策略不再执行。

例如：

```text
misfire too stale
```

---

# 78. Reconciliation

必须有轻量 consistency scan。

检查：

```text
ACTIVE Automation但next_trigger异常

MATERIALIZED Occurrence缺Job

stale definition revision Occurrence仍non-terminal

READY Job对应Occurrence已CANCELLED
```

Reconciliation 不是第二 Scheduler truth。

---

# 79. Cancel Race

若 Cancel 先 commit：

```text
Scheduler扫描不到ACTIVE Automation
```

若 Scheduler先 materialize：

```text
Cancel transaction
→ Automation CANCELLED
→ eligible non-terminal Occurrence CANCELLED
→ cancel READY Job where safe
```

Worker side effect 前再最终 revalidate。

---

# 80. Reschedule Race

Definition change：

```text
definition_revision++
```

旧 revision 未完成 Occurrence：

```text
CANCELLED
```

执行前发现 stale revision：

```text
no side effect
```

---

# 81. ThingDate Correction Race

Correction transaction：

```text
ThingDate update
+
RELATIVE recompute
+
definition_revision++
+
old revision occurrence cancellation
```

同一 PostgreSQL transaction 尽量完成。

---

# 82. CONDITION 正式定义

> **在有限生命周期内重复观察一个条件，并在首次确认成立时触发后续动作的 durable one-shot watch。**

---

# 83. CONDITION 不是长期 Agent

长期存在的是：

```text
Automation
```

每次检查只是：

```text
Occurrence
```

必要时创建：

```text
fresh bounded Run
```

不让一个 LangGraph Thread 活几个月。

---

# 84. One-shot Watch

V2.2：

```text
首次 MET
→ Automation COMPLETED
```

不做：

```text
持续多事件subscription
change stream
every new announcement notification
```

---

# 85. ConditionSpec

采用：

```text
canonical natural criterion
+
structured control metadata
```

不做全自然语言黑盒，也不做完整 DSL。

---

# 86. ConditionSpec Logical Model

```text
criterion

source_plan:
  EXACT_URL
  WEB_SEARCH

evaluation_mode:
  DETERMINISTIC
  AGENT_BOUNDED

check_cadence:
  FIXED_INTERVAL
  LOCAL_RECURRENCE

starts_at?

expires_at

max_checks

execution_scope
```

---

# 87. criterion

创建时 Executive 必须把上下文依赖消掉。

用户：

> “官网出成绩以后告诉我。”

应 normalize 成类似：

```text
“2026软件杯官方正式成绩已经公开发布并可供用户查询。”
```

而不是未来每次去翻旧 Thread。

---

# 88. source_plan

V2.2：

```text
EXACT_URL
WEB_SEARCH
```

足够。

---

# 89. EXACT_URL

用户已给明确 URL：

```text
allowed tool
→ url_inspect
```

不默认 search_web。

---

# 90. WEB_SEARCH

未知 exact page：

```text
search_web
↓
url_inspect
```

通常：

```text
source_preference = OFFICIAL_FIRST
```

---

# 91. Evaluation Mode

正式：

```text
DETERMINISTIC
AGENT_BOUNDED
```

---

# 92. Deterministic First

能用结构化 predicate 稳定判断：

```text
不调用LLM
```

降低：

- 成本；
- 漂移；
- 延迟；
- 失败面。

---

# 93. Agent-bounded Evaluation

只有：

> 页面语义真正需要自然语言理解

时才用。

---

# 94. Run Origin

Condition Agent Run：

```text
origin = AUTOMATION_CONDITION
```

不是 Interactive。

---

# 95. Fresh Run

每个 Condition Occurrence：

```text
new bounded Run
```

不复用一个长期 Thread。

---

# 96. Minimal Run Context

只加载：

```text
criterion
source plan
current time
bounded linked Thing context if needed
ExecutionScope
budget
```

默认不加载：

```text
whole Thread
Long-term Memory
无关Files
无关Things
```

---

# 97. Allowed Tools

EXACT_URL Watch：

```text
url_inspect
```

WEB_SEARCH：

```text
search_web
url_inspect
```

必要时 MAY：

```text
state_get_thing_context
```

默认没有所有 Write Tool。

---

# 98. Background Run 无 State Mutation 权限

Condition Run 默认不能：

```text
thing_create
thing_change_state
task_create
task_change_status
thing_date_set
memory_remember
memory_forget
automation_create
automation_cancel
delete tools
```

观察不等于写现实的授权。

---

# 99. Background Run 不走 HITL 扩权

如果超出 delegated scope：

```text
DENY
```

不能：

```text
interrupt
等待用户授权几天
```

必要澄清必须在创建 Watch 时完成。

---

# 100. Condition Evaluation Output

统一：

```text
result:
  MET
  NOT_MET

summary

supporting refs?

run_id?

usage summary?
```

执行失败不伪装成 NOT_MET。

---

# 101. NOT_MET

含义：

> 本次检查正常完成，但未建立 Condition 已成立。

Automation：

```text
保持ACTIVE
```

用户默认不收到通知。

---

# 102. FAILED

含义：

```text
Search outage
URL timeout
Model failure
budget exhausted
```

Automation 通常仍：

```text
ACTIVE
```

等待下一次 cadence。

---

# 103. MET

映射：

```text
Occurrence → SUCCEEDED

Automation
ACTIVE → COMPLETED

completion_reason = CONDITION_MET

next_trigger_at = NULL
```

---

# 104. Condition Cadence

支持：

```text
FIXED_INTERVAL
LOCAL_RECURRENCE
```

---

# 105. FIXED_INTERVAL

适合：

```text
每4小时检查
每12小时检查
```

---

# 106. LOCAL_RECURRENCE

适合：

> “每天早上8点帮我查一次。”

复用 Recurrence + IANA timezone。

---

# 107. Minimum Cadence

平台 MUST 有：

```text
minimum condition interval
```

用户不能创建每10秒 Web Search。

具体数值 Deferred。

---

# 108. Default Cadence

用户未指定：

```text
Product Automation Policy
→ deterministic default
→ persist
```

不能每次由 LLM 动态决定。

---

# 109. No Adaptive Polling

V2.2 不做：

```text
快到日期自动每10分钟查
平时每12小时查
```

Deferred。

---

# 110. Finite Expiry

每条 CONDITION MUST 有：

```text
effective expires_at
```

用户未指定时：

```text
Product Policy
→ 默认 horizon
→ 创建时持久化 absolute expiry
```

---

# 111. 为什么必须有限

防止：

```text
Search
Model
Search
Model
```

永远运行。

V2.2 不承诺永久 Web monitoring。

---

# 112. max_checks

除 expires_at 外 MAY/SHOULD 有：

```text
max_checks
```

作为执行数量上限。

---

# 113. check_count

Automation MAY 保存：

```text
check_count
```

与 Occurrence materialization 同 transaction 增加。

DurableJob 内部 transient retry 不重复计数。

---

# 114. Expiry / Check Limit

达到：

```text
expires_at
或
max_checks
```

未 MET：

```text
Automation → COMPLETED

completion_reason:
  EXPIRED
  CHECK_LIMIT_REACHED
```

不是 FAILED。

---

# 115. Per-check Budget

每次 Condition Run 使用严格 profile：

```text
max_model_steps
max_tool_calls
max_search_web_calls
max_url_inspect_calls
max_input_tokens
max_output_tokens
```

具体数值 Deferred。

---

# 116. 不保存美元 Cost Budget

不用：

```text
max_cost_usd
```

因为 Provider 价格会变。

使用跨 Provider 的 usage limit。

---

# 117. Condition Run 比 Interactive 更严格

后台 Condition：

```text
更少Tool
更少Steps
更少Search
更小Context
更短timeout
```

避免长期成本累积。

---

# 118. Budget Exhaustion

单次：

```text
Occurrence → FAILED
```

Automation 默认继续。

不立即取消整个 Watch。

---

# 119. Condition Failure 不加第二套 cadence

DurableJob 负责本次 transient retry。

最终失败后：

```text
回到正常Condition cadence
```

不再建独立 backoff scheduler。

---

# 120. First Check

默认：

```text
next_trigger_at ≈ now
```

尽快第一次检查。

用户明确指定 future start 时才延后。

---

# 121. Single-flight Condition

同一 CONDITION：

```text
最多一个 non-terminal evaluation Occurrence
```

避免：

- 并行重复 Search；
- 双 MET；
- 双通知；
- 预算浪费。

---

# 122. Condition Evaluation 不单建表

不需要：

```text
ConditionEvaluation
```

因为已有：

```text
Occurrence
Run
ToolExecution
```

足够。

Occurrence MAY 保存 bounded evaluation receipt。

---

# 123. Selective Evidence Promotion

NOT_MET：

```text
runtime result + bounded summary
```

默认不永久保存大量 WebObservation。

MET：

```text
promote key source
→ WebObservation / EvidenceRef
```

用于长期解释。

---

# 124. Condition Timeline

普通：

```text
NOT_MET
FAILED
```

不进入用户 Timeline。

只有：

```text
MET
Watch expired
User cancel
```

MAY 形成 curated TimelineEvent。

---

# 125. Condition 不污染 Memory

NOT_MET 不形成 Memory。

Background Run 默认无：

```text
memory_remember
```

权限。

---

# 126. definition_revision

第三轮正式将之前的 `schedule_revision` 精化为：

```text
definition_revision
```

表示：

> 任何影响未来 Occurrence 执行语义的 Automation definition generation。

---

# 127. definition_revision Bump

以下变化：

```text
schedule
timezone
relative anchor/rule
condition criterion
source plan
execution scope
cadence
```

均：

```text
definition_revision++
```

纯 display rename MAY 不 bump。

---

# 128. version vs definition_revision

```text
version
= whole object concurrency

definition_revision
= future execution semantic generation
```

Occurrence 保存：

```text
definition_revision snapshot
```

执行前发现 stale：

```text
CANCELLED
```

---

# 129. Notification Layer

Occurrence 到点或 Condition MET 后：

> 系统已经决定“应该告诉用户”。

此时进入：

```text
NotificationIntent
```

而不是直接调用 Huawei Push。

---

# 130. NotificationIntent 定义

> **一次稳定、用户级、Provider-neutral 的通知事件。**

---

# 131. NotificationIntent Logical Model

```text
notification_id
owner_user_id

kind

source_occurrence_id?
source_automation_id?

title
body

deep_link_target?

created_at
expires_at?

cancelled_at?
```

---

# 132. Notification Kind

保持小枚举：

```text
REMINDER
CONDITION_MET
CONDITION_WATCH_ENDED
```

不把 Provider/Device 混进去。

---

# 133. Notification Content Freeze

NotificationIntent 创建时：

```text
title
body
```

就确定。

Push Worker 不调用 LLM 重写。

---

# 134. Reminder Content

通常：

```text
Automation.intent
+
deterministic template
```

就够。

---

# 135. Condition Content

来自：

```text
ConditionEvaluationResult.summary
+
deterministic notification template
```

LLM只参与条件判断，不参与 retry-time文案生成。

---

# 136. DeepLinkTarget

保存结构化内部目标：

```text
target_kind
target_id
```

例如：

```text
THING
TASK
AUTOMATION
NOTIFICATION
```

Provider Adapter / Client 再映射实际 route。

---

# 137. NotificationDelivery

> **一个 NotificationIntent 通过一个具体 Channel 向一个具体 Endpoint 的 durable delivery identity。**

---

# 138. NotificationDelivery Logical Model

```text
delivery_id
notification_id

channel
endpoint_id

status

provider_request_id?
provider_message_id?
provider_notify_id?

last_error_code?
attempt_count

accepted_at?
delivered_at?

created_at
updated_at
```

---

# 139. Delivery Channel

V2.2：

```text
HUAWEI_PUSH
```

就够。

---

# 140. Delivery Status

正式：

```text
READY
ACCEPTED
DELIVERED
FAILED
UNKNOWN_OUTCOME
CANCELLED
```

---

# 141. READY

Delivery durable，但还没有明确 Provider 接受。

不复制 DurableJob 的运行状态。

---

# 142. ACCEPTED

只表示：

> Provider 明确接受 Push 请求。

不等于：

> Device 已显示。

---

# 143. DELIVERED

只有获得真实 provider/client delivery receipt 时才进入。

如果没有可靠 receipt：

```text
ACCEPTED
```

就是服务端可信的最高状态。

---

# 144. 不做 DISPLAYED / OPENED

这些属于：

```text
client analytics
```

未来可以有 `NotificationOpened` Event，但不进入 Delivery 状态机。

---

# 145. FAILED

明确失败且没有安全自动恢复路径。

例如：

```text
invalid token
invalid payload
permanent permission/config failure
retry budget exhausted after definite failures
```

---

# 146. UNKNOWN_OUTCOME

例如：

```text
Huawei request可能已到Provider
↓
本地timeout
↓
无response
```

不知道：

```text
没送到
or
Provider已接受但response丢失
```

此时：

```text
UNKNOWN_OUTCOME
```

禁止 blind retry。

---

# 147. 不声称 Exactly-once Push

正式语义：

```text
Internal:
at-least-once durable execution
+
strong business dedupe

External:
provider-dependent
+
unknown-outcome protection

NOT:
exactly-once delivery
```

---

# 148. Push Duplicate Protection

三层。

---

# 149. NotificationIntent Unique

逻辑：

```text
(source_occurrence_id, notification_purpose)
```

同一 Occurrence 只能生成一个用户级通知事件。

---

# 150. NotificationDelivery Unique

逻辑：

```text
(notification_id, channel, endpoint_id)
```

同一 Notification 同一 Endpoint 只能有一个 logical Delivery。

---

# 151. DurableJob Dedupe

逻辑：

```text
PUSH_DELIVERY:{delivery_id}
```

---

# 152. Transactional Notification Creation

Reminder reaction：

```text
BEGIN

revalidate Automation / Occurrence

create NotificationIntent

select eligible PushEndpoints

create NotificationDelivery(s)

create PUSH_DELIVERY DurableJob(s)

Occurrence → SUCCEEDED

if one-shot:
    Automation → COMPLETED

COMMIT

best-effort Redis wake-up
```

---

# 153. CONDITION MET Transaction

```text
BEGIN

revalidate
promote key Evidence

Occurrence → SUCCEEDED

Automation:
ACTIVE → COMPLETED
completion_reason=CONDITION_MET
next_trigger_at=NULL

create NotificationIntent

fan-out Delivery(s)

create Push Jobs

COMMIT
```

---

# 154. Occurrence SUCCEEDED 最终定义

> **这一次 Automation 所要求的业务 reaction 已 durable COMMIT。**

对于 Reminder：

```text
NotificationIntent durable
```

即可。

不要求：

```text
Huawei accepted
Device delivered
```

---

# 155. Push Failure 不回滚 Occurrence

例如：

```text
Occurrence SUCCEEDED
NotificationIntent durable
Delivery FAILED
```

完全合法。

Automation Domain 不被 Push Provider 污染。

---

# 156. CONDITION EXPIRED 通知

V2.2：

```text
EXPIRED
CHECK_LIMIT_REACHED
```

默认产生一次低打扰用户通知：

> 监控已结束，目前未检测到结果。

普通 NOT_MET / 偶发 FAILED 继续静默。

---

# 157. NotificationIntent 与 Outbox

不新增：

```text
NotificationOutbox
```

因为：

```text
NotificationIntent
+
NotificationDelivery
+
DurableJob
```

已经实现 transactional outbox 所需的：

```text
business commit
+
durable external work
```

同事务。

---

# 158. NotificationAttempt 不单建表

DurableJob 已经承载：

```text
attempt
lease
retry
```

NotificationDelivery 只保存当前/最终 Provider delivery state。

---

# 159. Multi-device

用户：

```text
1 user
→ many PushEndpoint
```

禁止：

```text
users.push_token
```

单 Token 模型。

---

# 160. PushEndpoint

复用用户/设备专项。

逻辑至少：

```text
endpoint_id
owner_user_id
device_id

provider = HUAWEI

push_token

active
notifications_enabled

last_registered_at
invalidated_at?
```

---

# 161. Automation 不保存 Push Token

Automation Domain 永远只面向：

```text
user
```

不面向某个 Token。

---

# 162. Delivery 保存 endpoint_id，不复制 token

Worker send-time：

```text
load current endpoint
↓
use current token
```

支持 token refresh。

---

# 163. Target Snapshot

NotificationIntent 创建 transaction 时：

```text
snapshot current eligible endpoint identities
```

之后新设备登录：

```text
不补发旧Notification
```

---

# 164. Fan-out Policy

V2.2 默认：

> 所有当前属于用户、ACTIVE、notification-enabled、具有有效 token 的 PushEndpoint。

不做：

```text
Primary Phone
Preferred Device
Device Routing Rules
```

---

# 165. 无 Eligible Endpoint

NotificationIntent 仍然成立。

```text
Delivery count = 0
```

Automation 不无限 retry。

App 后续可以显示通知记录。

---

# 166. Permission Off 不禁止创建 Automation

用户系统通知关闭：

```text
Automation仍允许创建
```

但 Create receipt/UI MAY 提醒：

> 当前设备未开启系统通知。

---

# 167. V2.2 每 Endpoint 独立 Push Request

不做 multi-token batch 优化。

优点：

- timeout范围小；
- invalid token定位明确；
- correlation清楚；
- UNKNOWN_OUTCOME只污染一个Endpoint。

---

# 168. HuaweiPushAdapter

边界：

```text
NotificationDelivery
↓
HuaweiPushAdapter
↓
Huawei Push Kit
```

Domain 不知道：

```text
JWT
projectId
Huawei payload
push type
provider HTTP details
```

---

# 169. Final Send Revalidation

Push Worker 真正调用 Huawei 前 MUST 再验证：

```text
User account ACTIVE?

Notification not cancelled?

Notification not expired?

Occurrence still valid?

Automation/lifecycle still permits?

Endpoint active?

notifications_enabled?

token exists?
```

失败：

```text
Delivery → CANCELLED / FAILED
```

不调用 Provider。

---

# 170. Task DONE / CANCELLED

所有仅服务于该 Task 的未来 Automation：

```text
→ CANCELLED
```

以及：

```text
non-terminal Occurrence
pending NotificationDelivery
READY Jobs
```

在尚未 externalized 时失效。

---

# 171. Task Reopen

不自动复活旧 Automation。

用户需要重新创建未来提醒。

---

# 172. Thing COMPLETE / CANCEL

linked ACTIVE Automation：

```text
→ CANCELLED
```

因为 Thing lifecycle 已结束。

---

# 173. Thing ARCHIVE

```text
Automation继续ACTIVE
```

Archive 只是 visibility/organization。

不能取消 Reminder。

---

# 174. Thing RESTORE / REACTIVATE

不会自动恢复之前取消的 Automation。

重新未来行为需要新的明确用户意图。

---

# 175. Thing DELETE

Dependency preview 必须告诉用户：

```text
将取消N个future Automation
```

确认后：

```text
Thing delete
+
linked Automation cancel
+
pending Occurrence cancel
+
pending Delivery cancel
```

一起处理。

---

# 176. ThingDate CORRECT

继续：

```text
RELATIVE recompute
definition_revision++
stale Occurrence CANCELLED
pending old Delivery CANCELLED
```

Absolute ONCE 不变。

---

# 177. ThingDate DELETE

linked RELATIVE：

```text
Automation CANCELLED
reason=ANCHOR_REMOVED
```

并使 pending Occurrence/Delivery 失效。

---

# 178. Automation Cancel

成功 transaction：

```text
Automation
→ CANCELLED
next_trigger_at=NULL

eligible non-terminal Occurrence
→ CANCELLED

pending not-yet-externalized Delivery
→ CANCELLED

READY Job
→ no longer executable
```

---

# 179. 已 ACCEPTED Push

Automation Cancel 不保证撤回：

```text
Delivery = ACCEPTED
```

的消息。

V2.2 不把 Provider-specific Push Recall 纳入 correctness。

---

# 180. Push Recall Deferred

即使 Provider 支持 recall：

V2.2 不承诺：

> 已发出的 Reminder 一定可撤回。

只保证：

> 尚未进入 external provider 的 future/pending delivery 一定能被阻止。

---

# 181. Push Retry Matrix

| Provider/Worker情况 | Delivery | Retry |
|---|---|---|
| 尚未调用Provider，本地暂时失败 | READY | 是 |
| Server auth credential失败 | READY | refresh credential后有限retry |
| 明确429/503/temporary failure | READY | bounded backoff |
| payload永久非法 | FAILED | 否 |
| device token明确invalid | FAILED | 否 |
| Provider明确接受 | ACCEPTED | 否 |
| receipt确认 | DELIVERED | 否 |
| timeout且可能已发送 | UNKNOWN_OUTCOME | 禁止blind retry |

---

# 182. Server Credential 与 Device Token 分离

```text
Server JWT/Auth
= 老实人调用Huawei的凭证

Device Push Token
= 目标App installation
```

二者故障完全不同。

---

# 183. Invalid Push Token

明确 invalid：

```text
Endpoint.active=false
invalidated_at=now
```

未来不再 fan-out。

客户端重新注册 Token：

```text
upsert/reactivate Endpoint
```

---

# 184. Push Token Refresh

不能假设 token 永久稳定。

客户端启动/refresh 时：

```text
upsert PushEndpoint
```

---

# 185. Push Token Security

Token 不得进入：

```text
LLM context
Tool Result
普通日志
Notification body
```

日志使用：

```text
endpoint_id
token hash suffix
```

---

# 186. Foreground App

Backend 不建设两套 Notification。

统一：

```text
NotificationIntent
```

客户端前台/后台只影响展示渠道。

客户端可使用：

```text
notification_id
```

做业务 dedupe。

---

# 187. Notification Expiry

NotificationIntent SHOULD 有：

```text
expires_at
```

send-time 已过期：

```text
Delivery → CANCELLED
reason=NOTIFICATION_EXPIRED
```

不发送陈旧提醒。

具体 TTL Deferred。

---

# 188. Deep Link Target 被删除

客户端：

```text
resolve target
↓
不存在
↓
fallback到Notification detail / related Thing / Home
```

Deep Link 是 navigation hint，不是强 FK。

---

# 189. Notification 与 Evidence

Notification 不复制完整 Evidence。

通过：

```text
source_occurrence_id
```

间接关联 Occurrence evaluation receipt / Evidence。

---

# 190. Notification 不是 Authority

Notification 是 derived presentation artifact。

不能因为：

```text
通知里写了“成绩公布”
```

就变成 Personal State truth。

---

# 191. Notification 与 Timeline

MAY 进入 Timeline：

```text
Reminder fired
Condition MET
Watch expired
```

不进入 Timeline：

```text
Huawei retry
token invalid
Delivery ACCEPTED
```

---

# 192. Account Delete Fence

账户进入删除：

```text
block new Automation
block new Occurrence
block new NotificationIntent
block new Delivery
```

---

# 193. Account Delete Cleanup

```text
ACTIVE Automation → CANCELLED
non-terminal Occurrence → CANCELLED
READY Delivery → CANCELLED
Push Jobs → no longer executable

PushEndpoint → purge
Notification history → purge
Automation/Occurrence → purge
```

并继续整个 Account Delete workflow。

---

# 194. Account Delete Worker Revalidation

Push Worker即使已 CLAIMED：

调用 Huawei 前：

```text
account still ACTIVE?
```

否则：

```text
Delivery CANCELLED
```

---

# 195. 已 Provider Accepted 的 Push

Account Delete 不保证：

> 已经发出去的通知从设备端历史消失。

未来 provider recall MAY 增强，但不是 correctness 基础。

---

# 196. 客户端 Token Delete

客户端 MAY best-effort：

```text
deleteToken
unbind profile
```

但 Backend Account Delete 不能依赖客户端在线。

---

# 197. Final Logical Data Model

本专项新增的真正核心对象：

```text
Automation

Occurrence

NotificationIntent

NotificationDelivery
```

继续复用：

```text
DurableJob

Run
ToolExecution

User
Device
PushEndpoint

Thing
Task
ThingDate

Evidence
WebObservation
```

---

# 198. Typed Value Objects

可以先作为 typed value object：

```text
RecurrenceSpec
RelativeRule
ConditionSpec
ExecutionScope
DeepLinkTarget
```

不必都单独建表。

---

# 199. 不新增

```text
Timer
Trigger
SchedulerTask
AutomationJob
NotificationOutbox
NotificationAttempt
ConditionEvaluation
CronJob
PushMessage
ProviderMessage
```

除非未来真实需求证明。

---

# 200. Final Architecture

```text
User Intent
    │
    ▼
Automation
    │
    │ next_trigger_at
    ▼
Scheduler
    │
    ▼
Occurrence
    │
    ▼
DurableJob
    │
    ├─────────────────────────┐
    │                         │
    ▼                         ▼
Direct Reminder       Condition Evaluation
                              │
                       deterministic
                           or
                     bounded Agent Run
                              │
                              ▼
                         MET / NOT_MET
                              │
                    ┌─────────┘
                    ▼
             Application Reaction
                    │
             PostgreSQL Transaction
                    │
        ┌───────────┼────────────┐
        ▼           ▼            ▼
   Occurrence   Automation   NotificationIntent
    SUCCESS      update            │
                                  │ fan-out
                         ┌────────┴────────┐
                         ▼                 ▼
                 NotificationDelivery   ...
                         │
                    DurableJob
                         │
                       COMMIT
                         │
                  Redis wake-up
                         │
                       Worker
                         │
                 HuaweiPushAdapter
                         │
                     Push Kit
```

---

# 201. Failure Matrix

| Failure / Race | V2.2 处理 |
|---|---|
| Scheduler lock后crash | transaction rollback，下轮重新扫 |
| Occurrence insert后crash | rollback |
| Occurrence+Job后、next advance前crash | rollback |
| COMMIT后Redis publish前crash | Postgres Job truth，polling执行 |
| 多Scheduler扫同slot | SKIP LOCKED + UNIQUE Occurrence |
| Duplicate Job create | occurrence-based dedupe |
| ONCE服务器停机 | FIRE_ONCE，受stale horizon限制 |
| Recurring停机多slot | 最多coalesce一个恢复slot |
| Condition停机 | 不backfill历史check，只做current check |
| Reschedule与Scheduler并发 | definition_revision使旧Occurrence失效 |
| ThingDate correction并发 | 同事务重算RELATIVE + stale cancel |
| Condition Provider outage | Occurrence FAILED，Automation继续 |
| Condition budget exhausted | Occurrence FAILED，Automation继续 |
| Condition NOT_MET | 静默，Automation继续 |
| Condition MET | SUCCEEDED + Automation COMPLETED + Notification durable |
| Notification创建前crash | transaction rollback，Occurrence不伪装成功 |
| Notification+Delivery+Job COMMIT后crash | DurableJob恢复 |
| Redis down | PostgreSQL Job truth |
| 同Occurrence reaction重复 | Notification business unique阻止 |
| 同Notification重复fan-out | Delivery unique阻止 |
| Worker重复claim | same Delivery / Job |
| Huawei明确accepted | ACCEPTED |
| Huawei success但设备未显示 | 仍只是ACCEPTED |
| Huawei receipt | DELIVERED |
| Huawei invalid token | Delivery FAILED；Endpoint invalid |
| Huawei auth过期 | refresh credential + retry |
| Huawei 429/503 | bounded retry |
| Huawei payload非法 | FAILED |
| Huawei timeout可能已发送 | UNKNOWN_OUTCOME；不blind retry |
| 用户先完成Task | cancel future Automation/Occurrence/Delivery |
| Push已accepted后Task完成 | 不承诺撤回 |
| Deadline改期且旧Delivery未发 | stale Delivery CANCELLED |
| Deadline改期但旧Push已accepted | 历史不能撤回，未来重算 |
| Thing Archive | Automation继续 |
| Thing Complete/Cancel | linked Automation取消 |
| Token refresh | send-time使用Endpoint当前token |
| Token invalid | Endpoint inactive |
| 新Device晚注册 | 不补发旧Notification |
| Notification permission关闭 | endpoint不eligible |
| 无endpoint | NotificationIntent仍存在，不无限retry |
| Notification过期 | Delivery CANCELLED |
| Account Delete时Job READY | cancel |
| Account Delete时Job CLAIMED未send | final fence阻止 |
| Account Delete时Push已accepted | 不承诺撤回 |
| Deep link target删除 | client fallback |
| Push content超限 | Adapter发送前确定性校验 |

---

# 202. V1 → V2.2 Migration

当前缺少权威 V1 Automation/Push 实际 Schema。

因此本文只冻结 Migration Strategy：

```text
EXPAND
↓
BACKFILL
↓
DUAL COMPATIBILITY
↓
CUTOVER
↓
VERIFY
↓
CONTRACT
```

不编造字段级 SQL。

---

# 203. Phase 1 — Expand

增加：

```text
Automation v2 fields

definition_revision
next_trigger_at

Occurrence

NotificationIntent
NotificationDelivery
```

复用：

```text
DurableJob
Device / PushEndpoint
```

旧 path 暂不删除。

---

# 204. Phase 2 — Legacy Reminder Mapping

旧：

```text
reminder_time
text
status
```

明确 single date/time：

```text
→ ONCE
```

明确 recurring rule：

```text
→ RECURRING
```

不确定时不要猜。

---

# 205. Legacy Absolute 不猜成 Relative

即使：

```text
18号Reminder
```

碰巧等于：

```text
Deadline -1 day
```

没有原始用户语义证据：

```text
保持ONCE
```

不能自动转 RELATIVE。

---

# 206. Phase 3 — Push Endpoint Backfill

旧：

```text
user.push_token
```

迁移为：

```text
PushEndpoint
```

如果无法恢复 Device identity：

```text
先映为一个legacy endpoint
```

不编造多个设备。

---

# 207. Phase 4 — Scheduler Cutover

上线：

```text
next_trigger_at scanner
Occurrence
DurableJob
```

必须定义：

```text
migration_cutover_at
```

确保旧 Scheduler 和新 Scheduler 不同时负责同一个 slot。

---

# 208. Phase 5 — Notification Cutover

新 Occurrence：

```text
NotificationIntent
→ Delivery
→ DurableJob
```

旧 direct-Huawei path 只处理 legacy work，随后 Contract。

---

# 209. 不编造 Historical Occurrence

如果 V1 没可靠执行历史：

不能：

```text
INSERT SUCCEEDED Occurrence
```

伪造成功记录。

应明确：

```text
legacy execution history unavailable
```

---

# 210. 官方设计依据

本文使用以下官方/成熟资料校准架构，但不机械照搬第三方平台。

## PostgreSQL

Row locking / SKIP LOCKED：

https://www.postgresql.org/docs/current/sql-select.html

Transaction isolation：

https://www.postgresql.org/docs/current/transaction-iso.html

用于校准：

```text
due scan
active-active scheduler
short transaction
SKIP LOCKED queue-like claim
```

---

## RFC 5545

iCalendar recurrence：

https://www.rfc-editor.org/rfc/rfc5545.html

用于校准：

```text
local recurrence
TZID
DST
COUNT
UNTIL
invalid local recurrence skip
```

V2.2 只采用一个小型子集。

---

## LangGraph

Persistence / threads / interrupts：

https://docs.langchain.com/oss/python/langgraph/persistence

https://docs.langchain.com/oss/python/langgraph/interrupts

用于校准：

```text
HITL waiting
≠ months-long Automation waiting

Condition check
→ fresh bounded Run
```

---

## Sidekiq

Scheduled Jobs：

https://github.com/sidekiq/sidekiq/wiki/Scheduled-Jobs

Reliability：

https://github.com/sidekiq/sidekiq/wiki/Reliability

用于校准：

```text
future timestamp
→ scheduler polling
→ execution queue
```

但老实人不采用 Redis 作为 schedule truth。

---

## Celery

Periodic Tasks / Timezone：

https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html

用于校准：

```text
periodic schedule
timezone
single/multiple scheduler concerns
```

但老实人不引入 Celery Beat 作为第二调度真相。

---

## Transactional Outbox

AWS Prescriptive Guidance：

https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html

用于校准：

```text
business state
+
durable external work
```

同事务，随后异步外发。

---

## Huawei Push Kit

Push Kit：

https://developer.huawei.com/consumer/en/hms/huawei-pushkit

HarmonyOS Push Service APIs：

https://developer.huawei.com/consumer/en/doc/harmonyos-references/push-pushservice

Push Specification：

https://developer.huawei.com/consumer/en/doc/harmonyos-guides/push-specification

用于校准：

```text
device token
notification permission
provider accepted ≠ device delivered
message receipt
token invalidation
message recall
```

---

# 211. Frozen Decisions

以下进入 Backend Freeze：

1. Automation 是 durable future intention，不是 Timer/Job。
2. Automation 与 Task、ThingDate、Occurrence、Run、Notification 分离。
3. 类型仅 ONCE / RECURRING / RELATIVE / CONDITION。
4. CRON、DELAY、WATCH 不作为独立 Domain Type。
5. ONCE authority 是创建时解析出的确定 UTC instant。
6. ONCE 不随设备旅行自动移动。
7. RECURRING authority 是 local recurrence + IANA timezone。
8. Recurrence只支持DAILY/WEEKLY/MONTHLY等有限subset。
9. 不完整实现RFC5545。
10. IANA timezone是Recurring/Relative长期authority。
11. Device timezone只用于创建/修改时解释。
12. User timezone只是fallback。
13. Server timezone不参与业务时间语义。
14. V2.2不支持floating-local schedule。
15. DST从local recurrence重新计算UTC，不固定加秒。
16. 不存在的DST local recurrence默认skip。
17. original_expression仅用于解释，不是scheduler authority。
18. Scheduler不得重复调用LLM解析schedule。
19. RELATIVE必须保存stable ThingDate anchor。
20. Relative rule区分calendar offset和duration offset。
21. Relative必须尊重ThingDate precision。
22. ThingDate correction同步重算RELATIVE。
23. ThingDate correction与RELATIVE重算尽量同一PostgreSQL transaction。
24. Anchor delete取消linked RELATIVE。
25. Absolute Reminder不跟随ThingDate correction。
26. Automation状态只ACTIVE/COMPLETED/CANCELLED。
27. 单次执行失败不让Automation FAILED。
28. PAUSED/Resume V2.2 Deferred。
29. Reschedule保留Automation identity。
30. Past Occurrence不因Reschedule改写。
31. `version`用于optimistic concurrency。
32. `definition_revision`用于future execution semantic generation。
33. `next_trigger_at`是统一Scheduler index。
34. 除ONCE外next_trigger_at不是schedule authority。
35. Scheduler truth在PostgreSQL。
36. Redis只wake-up。
37. Scheduler只发现due/materialize/enqueue，不做LLM/Search/Push。
38. 支持active-active Scanner。
39. SKIP LOCKED只用于queue-like claim。
40. Occurrence是一等durable entity。
41. Occurrence逻辑唯一键包含automation_id、definition_revision、scheduled_for。
42. Row lock负责并发效率，UNIQUE负责最终correctness。
43. 一个Occurrence只能有一个logical DurableJob。
44. Occurrence+Job+next-trigger advance同一transaction。
45. Scheduler transaction禁止external calls。
46. DB commit后才best-effort Redis wake-up。
47. 不提前物化大量未来Occurrence。
48. ONCE/one-shot RELATIVE materialize后next_trigger置空。
49. RECURRING每次从authority重新算下一slot。
50. Scheduler due比较优先使用DB时间。
51. 只承诺bounded scheduling lag，不承诺second-perfect。
52. 首版small bounded batch。
53. READ COMMITTED + row lock + UNIQUE为默认。
54. Deadlock按whole transaction retry。
55. Misfire只FIRE_ONCE/SKIP。
56. Recurring downtime最多coalesce一个恢复slot。
57. Condition历史check不backfill。
58. Occurrence状态为MATERIALIZED/SUCCEEDED/NOT_MET/FAILED/CANCELLED/SKIPPED。
59. Occurrence不复制Job RUNNING状态。
60. Reconciliation必须存在但不是第二truth。
61. Condition是finite one-shot watch。
62. Continuous subscription Deferred。
63. ConditionSpec使用canonical criterion + structured controls。
64. Condition不依赖旧Interactive Thread。
65. Source Plan主要EXACT_URL/WEB_SEARCH。
66. Condition evaluation只DETERMINISTIC/AGENT_BOUNDED。
67. 能deterministic就不调用LLM。
68. Agent evaluation每次使用fresh AUTOMATION_CONDITION Run。
69. Condition Run上下文最小化。
70. Condition Run默认无Memory和State write权限。
71. Background Run不得通过HITL扩权。
72. Condition必须structured MET/NOT_MET输出。
73. 技术失败不能伪装NOT_MET。
74. Cadence只FIXED_INTERVAL/LOCAL_RECURRENCE。
75. 平台必须存在最小condition interval。
76. Default cadence由Product Policy创建时持久化。
77. V2.2不做adaptive polling。
78. 每个CONDITION必须有finite expires_at。
79. Infinite Watch Deferred。
80. MAY/SHOULD有max_checks。
81. check_count与Occurrence materialization同事务更新。
82. Expiry/check-limit使Automation COMPLETED而非FAILED。
83. Condition MET使Automation COMPLETED。
84. completion_reason表达CONDITION_MET/EXPIRED/CHECK_LIMIT_REACHED等。
85. 每次Condition Run必须有严格usage budget。
86. 不用美元成本字段作为Domain authority。
87. Background budget比Interactive更严格。
88. Condition search/fetch次数必须限制。
89. 单次budget exhaustion只让Occurrence FAILED。
90. Condition失败后回正常cadence，不建第二scheduler。
91. First check默认尽快执行。
92. 同一Condition最多一个non-terminal evaluation occurrence。
93. 不建ConditionEvaluation表。
94. NOT_MET默认不永久保存所有WebObservation。
95. 普通NOT_MET/FAILED保持silent。
96. Condition不自动写Memory/State。
97. NotificationIntent是用户级durable notification event。
98. NotificationDelivery是每Endpoint external delivery identity。
99. 不新增独立NotificationOutbox表。
100. 一个Notification可fan-out多个Device Delivery。
101. Notification文案在业务transaction前确定。
102. Push Worker不调用LLM。
103. Delivery状态READY/ACCEPTED/DELIVERED/FAILED/UNKNOWN_OUTCOME/CANCELLED。
104. Provider明确成功只能映射ACCEPTED。
105. 只有真实receipt才映射DELIVERED。
106. 不建DISPLAYED/OPENED delivery state。
107. NotificationIntent按source occurrence做business dedupe。
108. Delivery按notification+endpoint+channel做unique。
109. Push DurableJob按delivery_id dedupe。
110. 不声称exactly-once Push。
111. timeout且outcome未知时进入UNKNOWN_OUTCOME，禁止blind retry。
112. Occurrence SUCCEEDED定义为business reaction已durable COMMIT。
113. Reminder的Notification/Delivery/Job与Occurrence结果同事务。
114. CONDITION MET的Evidence/Completion/Notification同事务。
115. CONDITION EXPIRED/CHECK_LIMIT默认产生一次watch-ended通知。
116. 普通NOT_MET/偶发FAILED不通知用户。
117. PushEndpoint按Device/App installation建模。
118. Delivery保存endpoint_id，不复制token。
119. Notification创建时snapshot当前eligible endpoint identities。
120. 新Device不补发旧Notification。
121. 默认fan-out所有eligible endpoints。
122. notification permission off不禁止创建Automation。
123. 无eligible endpoint时NotificationIntent仍成立。
124. 首版每Endpoint独立Huawei request。
125. Huawei细节只存在HuaweiPushAdapter。
126. 外部Push前必须最终lifecycle revalidation。
127. Task DONE/CANCELLED取消linked未来Automation。
128. Task reopen不自动恢复旧Automation。
129. Thing COMPLETE/CANCEL取消linked Automation。
130. Thing ARCHIVE不取消Automation。
131. Thing Reactivate/Restore不自动恢复旧Automation。
132. Thing DELETE取消linked future Automation。
133. ThingDate correction取消旧pending relative delivery并重算。
134. ThingDate delete取消linked RELATIVE。
135. Automation Cancel阻止尚未externalized的delivery。
136. 已ACCEPTED Push不保证可撤回。
137. Push Recall Deferred。
138. invalid Push Token立即invalidate Endpoint。
139. Server credential failure与Device token failure分离。
140. Token refresh通过Endpoint upsert。
141. Push Token不进入LLM/Tool Result/普通日志。
142. 前台/后台不建两套Notification Domain。
143. Notification SHOULD有delivery expiry。
144. Notification不是Personal State authority。
145. Account Delete先fence新Automation/Notification，再cancel/purge。
146. Account Delete过程中Worker send前再次检查account lifecycle。
147. 已Provider Accepted Push不保证从设备端撤回。
148. Notification history进入Account Purge。
149. V2.2不新增NotificationAttempt表。
150. V1→V2.2采用Expand→Backfill→Cutover→Verify→Contract。
151. Migration必须定义Scheduler cutover boundary。
152. Migration不得把历史absolute Reminder猜成RELATIVE。
153. Migration不得编造历史Occurrence成功记录。

---

# 212. Deferred Details

## Time / Recurrence

- 最终 temporal schema；
- Recurrence JSON/columns；
- daypart 默认映射；
- DST library；
- “月底”等高级规则；
- floating-local schedule。

## Scheduler

- scanner interval；
- batch size；
- exact SQL；
- indexes；
- deadlock retry limit；
- stale horizon；
- max lateness；
- scheduler instance count；
- reconciliation interval。

## Condition

- default cadence；
- minimum cadence；
- default expiry；
- max_checks default；
- budget values；
- source-plan canonical schema；
- evaluation receipt schema；
- user/plan quota。

## Notification

- Notification title/body最大业务长度；
- Notification expiry policy；
- watch-ended文案；
- deep-link route mapping；
- app notification history UI；
- notification center read model。

## Huawei Push

- exact V3 payload；
- JWT/service account实现；
- provider timeout；
- retry/backoff；
- receipt callback；
- notifyId生成规则；
- provider correlation字段；
- recall未来扩展。

## Multi-device

- PushEndpoint exact schema；
- device identity；
- permission sync；
- token rotation/upsert contract；
- endpoint cleanup。

## Lifecycle

- Task/Thing lifecycle exact Application use case transaction；
- cancellation dependency preview；
- in-flight provider request边界；
- account deletion exact workflow。

## Migration

- 当前V1真实表结构；
- legacy reminder mapping；
- legacy push token mapping；
- cutover时间；
- rollback window；
-旧scheduler shutdown步骤。

---

# 213. Backend Freeze 验收问题

开发进入实施前必须能回答：

## 1. Automation是什么？

用户授权系统未来执行某项行为的durable intention。

## 2. Task和Automation区别？

Task是用户未来做什么；Automation是系统未来做什么。

## 3. 为什么不把Reminder存在Timer里？

Timer不是durable truth，进程重启会丢；Automation存在PostgreSQL。

## 4. 为什么Recurring不能只存next_trigger_at？

因为下一次以后仍需要原始local recurrence+timezone语义。

## 5. 为什么不存Cron作为authority？

Cron无法完整表达用户时间语义、relative binding、end rule和产品语义。

## 6. 为什么Relative必须存ThingDate ID？

Deadline correction后Reminder必须跟随同一stable fact identity。

## 7. 为什么“前一天”不能直接减86400秒？

它是calendar semantics，DST下与exact duration可能不同。

## 8. 为什么需要Occurrence？

为了给每一次logical trigger独立identity、history、dedupe和misfire解释。

## 9. 两个Scheduler怎么避免重复？

`FOR UPDATE SKIP LOCKED`做并发分工，Occurrence UNIQUE做最终correctness。

## 10. Scheduler crash会丢Reminder吗？

不会，Automation/Occurrence/Job/next-trigger全在PostgreSQL durable transaction中。

## 11. Redis挂了呢？

Redis只是wake-up；Worker fallback polling读取PostgreSQL READY Job。

## 12. Condition为什么不是长时间Agent？

长期的是Automation；每次check是fresh bounded Run，避免巨大Thread和无限成本。

## 13. Condition为什么不会无限烧钱？

cadence + expiry + max_checks + per-check budget + restricted tools。

## 14. Condition没满足算失败吗？

不是，Occurrence=NOT_MET，Automation继续ACTIVE。

## 15. Provider查不到是NOT_MET吗？

不是，技术故障=FAILED。

## 16. 什么时刻Occurrence算SUCCEEDED？

Automation所要求的business reaction已经durable COMMIT；不要求Push已经送达。

## 17. 为什么需要NotificationIntent？

一个用户级通知可能fan-out多个设备，而且即使无Push设备仍有一个业务通知事件。

## 18. 为什么还需要NotificationDelivery？

每个设备Token、Provider结果、invalid token、receipt都独立。

## 19. Huawei返回成功算送达了吗？

不算，只算Provider ACCEPTED；有真实receipt才DELIVERED。

## 20. Push timeout怎么办？

如果不能确认Provider是否收到，进入UNKNOWN_OUTCOME，禁止blind retry。

## 21. 怎么防多设备重复？

一个NotificationIntent，每Endpoint一个unique Delivery。

## 22. Task提前完成后为什么不再提醒？

Task生命周期变化确定性取消linked future Automation和pending delivery。

## 23. Thing Archive为什么Reminder继续？

Archive只是visibility，不代表事情结束。

## 24. Deadline改期呢？

Relative重算并使旧definition pending occurrence失效；absolute不变。

## 25. Account Delete怎么阻止后台继续推送？

先fence新work，Worker external send前再次检查account lifecycle，再durable purge。

---

# 214. 一句话定义

> **老实人 Automation / Scheduler / Notification v2.2 是一套以 PostgreSQL 中的 Automation 作为未来意图真相、以 `next_trigger_at + active-active Scheduler + unique Occurrence + DurableJob` 可靠物化未来执行、以有限 cadence/expiry/budget 的 fresh bounded Agent Run 处理 Condition Watch、再以 NotificationIntent + per-device NotificationDelivery + HuaweiPushAdapter 完成最终用户通知的 durable future-action system；它明确拒绝把未来等待做成长时间 LangGraph Run、把 Redis/Timer 当调度真相、把 Provider Push 成功当用户已送达，也不声称 exactly-once external notification delivery。**
