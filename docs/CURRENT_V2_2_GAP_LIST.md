# Current V2.2 Gap List

更新时间：2026-08-30。Phase 0–8 核心开发已完成；下列为**仍与设计正式版有差距**或**生产发布前**待办项，不代表仓库无实现。

## 已收敛（原 Gap 关闭）

| 领域 | 状态 |
|------|------|
| DurableJob | AGENT_RUN、FILE_PURGE、MEMORY_FORMATION、AUTOMATION_OCCURRENCE、PUSH_DELIVERY、ACCOUNT_DELETION |
| Runtime / Tool | RunInteraction、SSE sequence、ledger replay、UNKNOWN_OUTCOME、`claim_ready_jobs` |
| Personal State | 21 capability、ThingContextEntry、merge/recurring/tombstone |
| File | V2 retrieval、FILE_PURGE、MessageAttachment、EvidenceRef |
| Memory | RRF、forget suppression、durable formation、state reconciliation（formation） |
| Automation / Notification | Occurrence → Intent → Delivery 管线；PushEndpoint |
| Identity | Session、Device/Push API、account deletion worker |
| Hardening | Freeze Gate B/C/D、契约 drift CI、Prometheus `/health/metrics`、隐私清单 |

## 仍开放 Gap

1. **Identity 生产化**：Huawei ID JWKS 校验、账号注销后 Things/Memory/Files 批量 purge。（`POST /auth/refresh` 已实现 session 轮换）
2. **Notification 生产化**：Huawei Push Kit 真适配；`notification_outbox` 表退役。
3. **Automation 契约切over**：API/Tool 仍部分 legacy enum（ONE_SHOT/PAUSED）；RELATIVE/CONDITION 调度与 misfire/condition budget 完整实现。
4. **Object Storage**：仍为本地 Adapter；生产 S3/对象存储与上传安全策略。
5. **Observability 深化**：OpenTelemetry tracing；除 backlog 外的 RED/USE metrics。
6. **Failure injection 矩阵**：Push/Search/模型 provider 广泛故障注入与发布阈值自动化。
7. **Gate A live CI**：`evals/test_live_agent_scenarios.py` 需 `RUN_MODEL_EVALS=1`，默认 CI 不跑。
8. **客户端**：HarmonyOS 除 Chat/SSE 外页面与 Device/Push 注册流程未完成。
9. **Source 遗留**：双读兼容层仍在；完全以 File 为唯一入口属后续清理。

## 发布前检查

见 [RELEASE_FREEZE_GATES.md](./RELEASE_FREEZE_GATES.md)。
