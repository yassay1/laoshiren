# Privacy Data Inventory (Backend V2.2)

更新时间：2026-08-30。本清单描述后端持久化与用户可导出数据的类别，供隐私政策与 Gate U5 对齐；具体保留期限以最终隐私政策为准。

## Identity & Session

| 数据 | 表/位置 | 敏感性 | 注销时处理 |
|------|---------|--------|------------|
| 内部 user_id | `users` | 标识符 | `DELETED` tombstone |
| Huawei external_subject | `users.external_subject` | 标识符 | 保留或匿名化（待政策） |
| Business Session token hash | `business_sessions` | 高 | `revoke` |
| Device 身份 | `devices` | 中 | `active=false` |
| Push token | `push_endpoints` | 高 | `invalidate` |

## Personal State（权威现实）

| 数据 | 表/位置 | 敏感性 | 注销时处理 |
|------|---------|--------|------------|
| Things / Tasks / Dates / Blockers | `things`, `tasks`, … | 用户内容 | 当前：停用账号；全量 purge Deferred |
| State mutations / timeline | `state_mutations`, `timeline_events` | 审计 | Deferred 批量 anonymize |

## Chat & Runtime

| 数据 | 表/位置 | 敏感性 | 注销时处理 |
|------|---------|--------|------------|
| Threads / Messages | `threads`, `messages` | 用户内容 | Deferred |
| Agent Runs / Events | `agent_runs`, `run_events` | 用户内容 + 元数据 | Deferred |
| LangGraph checkpoints | checkpoint tables | 用户内容派生 | 随 Run 清理策略 |

## Files & Evidence

| 数据 | 表/位置 | 敏感性 | 注销时处理 |
|------|---------|--------|------------|
| File metadata | `files` | 中 | `FILE_PURGE` job（逻辑删除后） |
| Object storage blobs | `var/objects` / 未来 S3 | 高 | physical purge worker |
| Source chunks / segments | `source_chunks`, `retrieval_segments` | 用户内容 | 随 File/Thing 生命周期 |

## Memory（非权威）

| 数据 | 表/位置 | 敏感性 | 注销时处理 |
|------|---------|--------|------------|
| Long-term memories | `memories` | 用户内容 | Deferred bulk delete |
| Forget suppressions | `memory_suppressions` | 中 | Deferred |
| Profile versions | `memory_profile_versions` | 用户偏好 | Deferred |

## Automation & Notification

| 数据 | 表/位置 | 敏感性 | 注销时处理 |
|------|---------|--------|------------|
| Automations | `automations` | 用户配置 | `cancel` on deletion |
| Occurrences / Intents / Deliveries | Phase 6 tables | 中 | 随 automation 停止 |
| Legacy notification_outbox | `notification_outbox` | 中 | 不再写入；清理 Deferred |

## 日志与 Redis（非权威）

| 数据 | 位置 | 敏感性 | 说明 |
|------|------|--------|------|
| Request access logs | 应用 stdout | 低–中 | 含 `request_id`、path、status；不记录完整 token |
| Redis rate-limit keys | Redis | 低 | 瞬态；非 durable truth |
| Redis runtime wake-up | Redis Pub/Sub | 低 | 非持久化事件 |

## 明确不记录

- 完整 Bearer access token、refresh token、push token（仅 hash 或截断）
- 模型 API key、Huawei client secret
- 完整用户上传文件内容到应用日志

## 账号注销当前行为（Phase 7）

1. `user.status = DELETING` → 入队 `ACCOUNT_DELETION` durable job  
2. Worker：取消 automation、失效 push、停用 device、撤销 session、`DELETED`  
3. **未**自动删除：Things、Memory、Files、Threads（需后续 purge 阶段与法律保留策略）
