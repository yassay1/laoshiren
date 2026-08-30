# Phase 6 Completion Plan

目标：Automation Occurrence durable 物化、NotificationIntent/Delivery/PushEndpoint 管线，并逐步收缩 legacy `notification_outbox`。

设计权威：《老实人_Automation_Scheduler_Notification技术设计_v2.2.md》。

## P6.1 — Occurrence + DurableJob Materialization

状态：**完成**

- migration `20260830_0040_automation_occurrence_notification.py`
- `automation_occurrences` 表 + `(automation_id, definition_revision, scheduled_for)` 唯一约束
- `application/automations/materialize.py`：`materialize_due_automation`
- `process_due()` 改为 Occurrence + `AUTOMATION_OCCURRENCE` DurableJob（不再写 outbox）
- `automations.definition_revision` + `misfire_policy`

## P6.2 — NotificationIntent / Delivery / PushEndpoint

状态：**完成（schema + pipeline）**

- `notification_intents`、`notification_deliveries`、`push_endpoints` 表
- `application/automations/notification_pipeline.py`：Reminder Intent + per-endpoint Delivery + `PUSH_DELIVERY` job
- `RecordingNotificationAdapter.submit_delivery` 用于 Phase 6 测试/dev

## P6.3 — Workers

状态：**完成**

- `workers/automation_occurrence.py`：claim `AUTOMATION_OCCURRENCE` → Agent Run + Intent
- `workers/push_delivery.py`：claim `PUSH_DELIVERY` → adapter
- `AutomationScheduler` 串联 `process_due` + occurrence + push workers

## P6.4 — Legacy Outbox Shrink

状态：**部分完成**

- 新 due 路径不再写 `notification_outbox`
- `dispatch_pending()` 保留供 legacy 行与集成测试；API `GET /automations/notifications` 仍读 outbox
- 后续 migration 可 deprecate outbox 表

## P6.5 — V2.2 Automation Types / Condition / Relative

状态：**Deferred（Phase 6.1 后续）**

- DB enum 已扩展 `ONCE` / `RELATIVE` / `CONDITION`；API/Tool 仍暴露 legacy `ONE_SHOT` / `CONDITION_WATCH`
- `CONDITION` 评估、budget、`CONDITION_WATCH_ENDED` intent
- `RELATIVE` ThingDate anchor 调度
- `definition_revision` bump on reschedule API
- OpenAPI/Tool enum cutover + backfill

## Phase 6 Exit Criteria（核心已满足）

1. Due Automation 物化为 Occurrence + `AUTOMATION_OCCURRENCE` job（原子 UoW）。
2. Occurrence worker 创建 `NotificationIntent` + `PUSH_DELIVERY` jobs。
3. Push delivery worker 通过 adapter 送达（Recording adapter in dev）。
4. Agent Run 由 occurrence 路径触发（`test_automation_agent_run`）。
5. Legacy outbox dispatch 与 lease 测试仍可通过手动 seed 验证。

## 明确 Deferred（Phase 7+）

- Huawei Push Kit adapter、Device/PushEndpoint HTTP API
- 完整 CONDITION 评估与 finite budget
- RELATIVE recurrence 与 IANA timezone 规则引擎
- `notification_outbox` 表删除
