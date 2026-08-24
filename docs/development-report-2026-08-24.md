# 老实人后端可靠性开发报告（2026-08-24）

## 1. 本轮开发目标

本轮以当前代码、七份 v1.0 设计文档和 `docs/CURRENT_IMPLEMENTATION.md` 的审核结论为依据，优先修复 Agent Runtime 的真实运行风险，并把 Memory、Source、Automation 从孤立资源推进到可运行纵向链路。HarmonyOS 仅修改 HITL 与重试联调所需代码。

## 2. 本轮实际完成内容

- 建立零提交仓库的安全 Git baseline；确认 `.env`、缓存、构建产物和本地规划记录未提交。
- 修复 HarmonyOS confirmation response 与 LangGraph 的 payload 不一致。
- Graph 增加每 Run 12 次 Executive decision、8 次 Tool 调用的确定性预算。
- 把 LangGraph checkpoint `thread_id` 从业务 Thread ID 改为 Run ID。
- 服务启动恢复 QUEUED Run，并将崩溃遗留 RUNNING Run 乐观并发地恢复为 QUEUED 后重新派发。
- checkpoint Graph State 中的 DecisionKind、ToolStatus、ToolRisk 改存纯字符串，降低跨进程序列化/白名单风险。
- 客户端 retry 复用原 Run idempotency key，避免网络错误后重复创建 Run 与用户消息。
- Agent 运行前加载 PROFILE 与受限 SEMANTIC/EPISODIC Memory；上下文注入模型 Gateway。
- 只对用户显式“请记住：…”或“记住我…”形成长期记忆；按 Run 幂等并做规范化内容去重。
- Source 支持 TXT、Markdown、文本型 PDF 提取；处理结果、失败码和时间持久化。
- 用户消息引用的 READY Source 以最多 5 个、总计 12,000 字符的限额进入 Agent context。
- Automation scheduler 随服务启动/停止；due claim、occurrence 去重、outbox dispatch 与最多 3 次失败重试形成最小闭环。
- 新增 Source migration，刷新 OpenAPI，补齐专项单元/集成测试。

## 3. 修改的系统架构

依赖方向保持为 `Presentation / Worker / Agent Adapter -> Application -> Domain ports <- Infrastructure`。新增的 Memory context/formation 位于 Application；Source parser 和本地对象读取位于 Infrastructure；Agent Worker 只调用 Application service。所有装配仍集中在 `bootstrap.py`，生命周期控制在轻量 `main.py` 中。

业务 Thread 与 checkpoint execution 已明确分离：Thread 只承载跨 Run 对话历史，Run 是一次可暂停/恢复的执行生命周期，LangGraph 使用 `Run.id` 作为 checkpoint `thread_id`。

## 4. 当前真实 Agent 执行链

`POST /runs -> RuntimeApplicationService 原子创建 Run + USER Message + Event -> dispatcher -> AgentRunWorker -> Memory/Source context load -> LangGraph Executive -> Policy -> Tool Adapter -> Application use case -> Run Event -> response/interrupt -> Message + terminal Run`。

模型每次只做一个 decision。敏感 Tool 进入 confirmation interrupt；确认后同一 Run ID 恢复 checkpoint。Graph 超预算时 Run 以 `AGENT_BUDGET_EXCEEDED` 失败。

## 5. Memory 当前实现链路

- `AgentMemoryApplicationService.load_context` 精确读取 ACTIVE PROFILE（默认 6 条）。
- SEMANTIC（默认 6 条）与 EPISODIC（默认 3 条）分别检索，再按 importance/confidence/update time 合并裁剪。
- 已提供可配置的 OpenAI-compatible Embedding Gateway，并在 Composition Root 注入 Agent Memory；配置 model/base/key 后走现有 1536 维 pgvector cosine retrieval。provider HTTP/响应/维度异常会归一化并回退文本检索，Memory formation 仍保存内容但 embedding 留空，不使 Agent Run 失败。
- Model Gateway 只接收裁剪后的 `memory_context`，不会加载全部 Memory。
- `form_from_user_input` 只处理显式长期记忆意图；普通聊天、Thread 历史、checkpoint 与当前 Personal State 不写入长期记忆。
- 相同规范化内容不重复创建；创建使用 `agent-memory:{run_id}` 幂等键。PROFILE 可带稳定 `profile_key`；同用户同 key 更新使用事务 advisory lock，原子 supersede 旧 ACTIVE 值，新记录保存 `supersedes_id`，部分唯一索引保证最多一个 ACTIVE。既有 update API 继续提供 version、supersede、soft delete 和 operation idempotency。

## 6. Source 当前实现链路

`Upload -> extension/MIME/signature/size validation -> LocalObjectStorage + SHA-256 -> PENDING Source row -> SourceProcessingScheduler -> atomic claim/lease/heartbeat -> TextSourceParser -> READY/FAILED/retry -> USER Message source_ids -> AgentRunWorker bounded context`。

上传请求不再执行 PDF/TXT/Markdown 解析。`SourceProcessingWorker` 从 Application 领取任务；Repository 使用 PostgreSQL queue-like claim，最多 3 次有上限指数退避。解析器确定性失败直接终止，存储等基础设施异常进入 retry；Worker 崩溃后 lease 到期可被其他实例接管，旧 owner 的迟到完成写入会被拒绝。图片、Office、音频仍保持 PENDING，等待未来 parser adapter。

PDF 解析增加加密文件拒绝、最大页数、单页字符、总字符和 Application 超时边界。READY 写入与 `source_chunks` Evidence 块在同一事务完成；每块包含稳定 `id/ordinal/char_start/char_end`。Agent 按最多 5 个 Source、每 Source 最多 8 块和总计 12,000 字符组装 context，并携带 chunk_id。迁移前 READY 数据保留 extracted_text 兼容回退。

TXT/Markdown 使用 UTF-8（含 BOM）解析；PDF 使用 pypdf 提取文本。空文本、损坏 PDF 记录 `FAILED / SOURCE_PARSE_FAILED`，不伪装 READY。图片、Office、音频仍保持 PENDING，等待未来 OCR/Office/image/STT adapter。

## 7. Runtime / checkpoint / resume / recovery 实现

- Run ID 是 checkpoint execution key；同一 Run resume 复用，不同 Run 隔离。
- WAITING_USER 的业务 interrupt_id 与 LangGraph checkpoint 分工明确：前者校验 API resume，后者恢复 Graph node。
- 启动时 `recover_pending_runs` 扫描 QUEUED/RUNNING；RUNNING 通过 version compare-and-swap 回到 QUEUED，并写 `status.updated` recovery event。
- SSE 继续以数据库 Run Event 为权威，支持 Last-Event-ID replay；重连不重新执行业务。
- create/resume/cancel 延续 DB unique key + RunOperation 约束；HarmonyOS retry 复用同一 create key。
- Personal State 副作用 Tool 继续使用确定性 action_id 和 Application idempotency key，checkpoint 重放不会重复落业务状态。
- worker 进程取消不会将 Run 错标 FAILED；遗留 RUNNING 在下次启动恢复。
- 后续 P0 批次已增加数据库 Run lease：Worker 使用原子条件更新 claim QUEUED 或 lease 已过期的 RUNNING，并持久化 `claim_owner / lease_expires_at / heartbeat_at / attempt_count`。
- Worker 默认每 15 秒 heartbeat、lease 默认 60 秒；未过期的 Run 不允许第二 Worker claim，过期后允许安全接管。
- WAITING_USER、COMPLETED、FAILED、CANCELLED 会释放 lease；旧 owner 不能再写 interrupt 或终态。
- create Thread/Run 及 Run operation 在 UoW 内使用 PostgreSQL transaction advisory lock 串行化相同 `user_id + idempotency_key`，并发首次请求稳定读取同一资源，不再依赖唯一约束异常。
- Tool 执行新增 durable ledger；同一 `Run.id + action_id` 只有一个执行 owner，完成结果持久化后 Graph replay 直接复用，不再次调用 handler。

## 8. Automation 当前执行链

`AutomationScheduler -> process_due -> SELECT FOR UPDATE SKIP LOCKED -> occurrence_key -> NotificationOutbox unique insert -> Automation advance/complete -> atomic outbox claim/lease -> commit -> NotificationPort -> owner-checked SUBMITTED/FAILED + next_attempt_at`。

Scheduler 默认 30 秒轮询并在启动后立即执行一次。外部 adapter 调用已移出数据库事务；FAILED outbox 使用有上限指数退避并仅在 `next_attempt_at` 到期后重新领取，最多 3 次。claim lease 允许崩溃后接管，旧 owner 不能覆盖新结果。NotificationPort 强制接收 occurrence key 作为下游 idempotency key；专项测试覆盖“下游成功、数据库 ack 前崩溃”后的重复提交去重。当前实现仍是 recording adapter，没有 HarmonyOS Push；Automation 与 Agent Run 保持边界，不会隐式启动 Executive Run。

## 9. 新增或修改的数据表 / migration

新增 `20260824_0008_source_extraction.py`：

- `sources.extracted_text TEXT NULL`
- `sources.processing_error VARCHAR(100) NULL`
- `sources.processed_at TIMESTAMPTZ NULL`

已实际验证 `0008 downgrade -> 0007` 与 `upgrade -> head` 往返成功。Runtime recovery 和 Automation retry 沿用既有表、状态与索引，无额外 migration。

后续新增 `20260824_0009_run_leases_tool_ledger.py`：

- `agent_runs.claim_owner / lease_expires_at / heartbeat_at / attempt_count`
- `ix_agent_runs_status_lease`
- `tool_execution_status` enum
- `tool_executions`：action identity、arguments hash、owner lease、attempt、status 与持久 ToolResult
- `uq_tool_executions_action(run_id, action_id)` 与 status/lease claim index

已实际验证 `0009 -> 0008 -> 0009` downgrade/upgrade 往返成功。

## 10. 新增 API / Tool / Worker / Adapter

- API：Source response/OpenAPI 新增 extraction 三字段；上传新增 `.txt`、`.md` 类型。
- Tool：未新增平行 Tool；既有 Personal State Tool 继续复用 Application。
- Worker：新增 `AutomationScheduler`；增强 `AgentRunWorker` 的 context、formation、checkpoint 和 budget failure 语义。
- Adapter：新增 `TextSourceParser`；`LocalObjectStorage` 新增受 object key 边界保护的 read。
- Application：新增 `AgentMemoryApplicationService` 与 `EmbeddingProvider` port；Runtime 新增 `recover_pending_runs`。

## 11. 关键代码位置

- `backend/src/laoshiren/agent/graph.py`：`build_executive_graph`，预算、HITL、Policy/Tool 路由。
- `backend/src/laoshiren/workers/agent.py`：`AgentRunWorker.run_once`，Run checkpoint、Memory/Source context、formation 与终态映射。
- `backend/src/laoshiren/application/runtime/service.py`：`recover_pending_runs`，启动恢复用例。
- `backend/src/laoshiren/application/runtime/service.py`：`claim_run`、`renew_run_lease`、`claim_tool_execution`、`complete_tool_execution`，多实例执行所有权用例。
- `backend/src/laoshiren/domain/runtime/entities.py`：`AgentRun.recover_after_crash`，恢复状态机。
- `backend/src/laoshiren/application/memories/context.py`：`AgentMemoryApplicationService`，检索组装与显式形成。
- `backend/src/laoshiren/application/sources/service.py`：上传校验、解析编排、处理状态持久化。
- `backend/src/laoshiren/infrastructure/sources/text_parser.py`：TXT/Markdown/PDF parser adapter。
- `backend/src/laoshiren/workers/automation.py`：持久状态 scheduler 生命周期。
- `backend/src/laoshiren/infrastructure/persistence/repositories/automations.py`：due/outbox 并发 claim 与 retry 查询。
- `backend/src/laoshiren/infrastructure/persistence/repositories/runtime.py`：Run 原子 lease claim、heartbeat 与 Tool ledger CAS。
- `backend/src/laoshiren/bootstrap.py`：全部新增依赖组装。
- `backend/src/laoshiren/main.py`：checkpoint、dispatcher、recovery、scheduler 的启动/停止顺序。
- `apps/harmonyos/.../ChatRepository.ets`、`ChatViewModel.ets`：HITL payload 与 retry key。

## 12. 测试结果

- 通过：ruff 全仓检查。
- 通过：mypy strict，100 个 source files。
- 通过：`RUN_DATABASE_TESTS=1 uv run pytest -q -m "not eval"`，38 passed。
- 通过：migration `0008 -> 0007 -> head` 往返。
- 通过：OpenAPI 重新生成，`git diff --check`。
- 未执行：`backend/evals/` 真实模型 eval；本轮避免依赖付费/不稳定模型调用。
- 未执行：HarmonyOS 真机/模拟器构建与 E2E；本轮仅做最小 contract 修复，未投入前端体验测试。

新增专项覆盖包括 Graph budget、Memory context/formation、Source text parsing、Automation scheduler lifecycle、Runtime restart recovery、5 路并发 Thread/Run 幂等、Run lease 竞争/过期接管/旧 owner 拒绝、Tool ledger busy/cache replay。既有测试继续覆盖 HITL interrupt/resume、checkpoint PostgreSQL、pgvector search、SSE Last-Event-ID、Tool/Application 与 Automation occurrence。

## 13. 已修复问题

- confirmation 的 `approved`/`action` 不一致。
- Graph 无 decision/tool-call 上限。
- enum 对 checkpoint serializer 不够保守。
- 业务 Thread 与 Graph checkpoint 生命周期混用。
- 重启后 QUEUED/RUNNING Run 永久遗失。
- HarmonyOS retry 产生新幂等键。
- Memory 不进入 Agent、也不形成。
- Source 只有仓储，不提供 extracted context。
- Automation 没有常驻 scheduler、FAILED outbox 不重试。

## 14. 尚未解决的问题

- Embedding Gateway 已可配置，但部署环境仍需提供实际 embedding model/base/key；未配置时明确使用文本检索降级。
- Memory formation 仍只覆盖显式中文触发语；回答风格和提醒偏好已有确定性 key-level supersede，但尚不是模型辅助的通用候选抽取和矛盾检测。
- Source 已有解析资源限制与文本 Evidence chunks，但尚无 OCR、Office、图片理解、STT、页码级 provenance 和 semantic chunk retrieval。
- Automation outbox 和 Port 已强制 occurrence key 幂等契约；真实 Push adapter 仍需确认目标服务确实持久实现该键，而不是只接受参数。
- RecordingNotificationAdapter 不是真实 Push adapter。
- InProcessRunDispatcher 仍是本地低延迟唤醒机制；周期性 `RunDispatchScanner` 已让每个实例从数据库发现 QUEUED/过期 RUNNING Run。扫描为 at-least-once，执行唯一所有权仍由数据库 claim 保证；尚未引入独立 broker，因此空闲扫描存在最多一个 poll interval 的延迟。
- Tool ledger 能防止已持久完成结果重放，并与现有 Application 幂等组成 at-least-once 安全链；对于“外部副作用成功、ledger complete 前崩溃”仍要求外部 Tool 使用下游 idempotency key，无法宣称任意外部系统 exactly-once。
- Run heartbeat 目前由同一 asyncio 事件循环驱动；CPU 阻塞型 adapter 必须移出事件循环，否则可能发生 lease 误过期。

## 15. 与七份 v1.0 设计文档的差异

- 文档将 thread_id 容易理解为会话标识；实现明确拆分为业务 `Thread.id` 和 LangGraph checkpoint `Run.id`。这是为避免跨 Run Graph State 污染的长期可维护修正。
- Source v1 设想完整异步多模态 processing；当前已完成持久异步文本/PDF worker 与字符区间 Evidence，未支持类型仍为 PENDING，尚无 OCR 和页码级 Evidence。
- Memory v1 允许更丰富自动形成；本轮采用显式用户意图白名单，优先避免错误长期记忆覆盖现实 State。
- Automation 当前 action 是 notification outbox，不直接触发 Agent；符合边界保守原则，但未达到完整自动 Agent action。

## 16. 当前技术债和风险

最高风险已从“没有执行所有权/跨节点无法发现任务”下降为外部副作用下游幂等和 heartbeat 运行隔离；其次是 embedding 凭据/模型部署、Source 页码 provenance/OCR、真实 Push adapter 和可观测性。模型 Gateway prompt 仍是静态工具说明，新增 Tool 时需要同步维护。当前开发环境使用固定 Bearer auth，不适合生产。

## 17. 当前项目完成度判断

后端已经从“单实例可恢复”推进到“数据库协调的多 Worker claim、heartbeat、过期接管、Tool replay ledger 与并发幂等均有真实集成测试”的阶段。Personal State/Runtime 基础较完整；Memory/Source/Automation 已有真实纵向第一版，但仍处于可验证 MVP，而不是生产完备。HarmonyOS 仍只适合作为聊天联调壳。

## 18. 建议回来后重点人工审核的代码

优先审核：

1. `AgentRunWorker.run_once` 的 Run-ID checkpoint、heartbeat task 与 lease 丢失语义。
2. Run repository 的原子 claim 条件、周期 `RunDispatchScanner` 与 `recover_pending_runs` 仅恢复 expired lease 的边界。
3. `AgentMemoryApplicationService` 的显式形成边界与 profile/semantic 分类。
4. Source repository 的 `SKIP LOCKED` claim、lease 接管、旧 owner 拒绝和 retry 终态边界。
5. Automation 外部调用持锁事务与 retry 策略；下一阶段应拆成短事务 claim/ack。
6. HarmonyOS retry 流程在网络“服务端已创建、客户端未收到响应”场景的行为。

## 19. 建议发送的真实聊天测试案例

以下消息建议按顺序测试，并观察 Chat、数据库 Run/Event/Message、Memory、Source、Automation 记录。方括号中的 ID 需替换为前一步返回或查询到的真实 ID。

1. 普通问答：`用两句话告诉我，你现在能帮我管理哪些事情？`
2. 创建 Thing：`帮我创建一个事项，名字叫“九月体检安排”。`
3. 创建 Task（多轮 Tool）：`给“九月体检安排”添加两个任务：预约医院、整理既往报告。` 若 Agent 一次只做一个 Tool，应继续要求完成剩余任务。
4. Deadline/HITL：`把“九月体检安排”的正式截止时间设为 2026-09-10 18:00，时区 Asia/Shanghai，确定性 CONFIRMED。` 检查 confirmation，先取消一次，再重发并确认。
5. Blocker：`“九月体检安排”现在卡在医院号源不足，请记录为 blocker。` 当前没有 blocker Tool，正确表现应是说明无法执行或询问，而不是假称已写入；这也是下一阶段缺口验证。
6. Memory 写入：`请记住：我做医疗安排时希望至少提前三天提醒。`
7. Memory 去重：原样再次发送上一句；确认没有第二条 ACTIVE Memory。
8. PROFILE：`记住我偏好简洁、直接的回答。`
9. PROFILE supersede：再发送 `记住我偏好详细回答并给出例子。`，确认旧回答风格为 SUPERSEDED、新值为唯一 ACTIVE；新建会话发送 `我偏好什么样的回答？`，检查只使用新值。
10. Semantic 跨 Thread：新建会话后发送 `关于医疗安排，你记得我的提醒偏好吗？`
11. Source：上传包含“体检地点：市中心医院三楼；携带身份证”的 `.txt` 或 `.md`，先轮询 Source API 直到状态从 PENDING 变为 READY，再在创建 Run 时带该 source_id，然后问 `根据我刚上传的文件，体检在哪里、要带什么？`
12. PDF Source：上传真实可复制文本 PDF，问其中一个明确事实；再上传扫描图片 PDF，确认它显示 FAILED 或无法提取，而不是编造内容。
13. interrupt/resume：触发 deadline confirmation 后关闭客户端，再打开并通过 `GET /runs/{id}` + event reconnect 恢复；确认 WAITING_USER 不丢失。
14. SSE reconnect：运行中断网，重连时发送最后一个 `Last-Event-ID`；确认事件只补发缺失部分，最终 Message 只有一条。
15. duplicate dispatch：发送消息后立即模拟客户端超时，用同一 Idempotency-Key 重试；确认返回同一 Run，只有一条 USER Message。
16. 服务重启恢复：在 Run 为 QUEUED 或 RUNNING 时重启后端；RUNNING lease 到期后确认出现 `reason=lease_expired` 的 status event，并继续到终态。
17. Tool replay：创建 Thing 的 Run 在 Tool 完成后、Graph 完成前重启；确认 deterministic action id/Application idempotency 使 Thing 不重复。
18. Automation：通过 API 创建 1 分钟内到期的一次性 Automation，等待 scheduler；确认只有一个 occurrence/outbox，状态进入 submitted。
19. Automation retry：让 notification adapter 返回失败，确认下一 scheduler tick 不会立即热重试；到达 `next_attempt_at` 后重试，attempt_count 到 3 后终止。
20. 失败恢复：让模型 provider 临时不可用，确认 Run 为 FAILED 且有 `AGENT_EXECUTION_FAILED`；恢复 provider 后用新 Run 重试，不应复用失败 Run 的 checkpoint。

## 20. 下一阶段建议

下一阶段 P0 应规定未来外部副作用 Tool 的下游 idempotency contract，并进一步隔离无法被 asyncio timeout 终止的解析线程。P1 配置实际 Embedding 服务并增加 Memory 通用 candidate extraction/矛盾检测 eval。P2 为 Source 增加页码 provenance、semantic chunk retrieval 与 OCR adapter。P3 接入真实 Push adapter 并验证其持久幂等能力，增加 outbox 可观测指标。前端继续维持联调范围。

## 最终仓库与验证快照

生成报告前：

```text
git log --oneline
917902c feat: add leased source processing worker
fa3384d feat: add durable run dispatch scanning
3f911dc docs: update audit for multi-worker execution safety
6fd42bd feat: add leased run claims and durable tool ledger
ee596e5 feat: harden agent runtime and connect durable context
2dea15b chore: establish audited project baseline

测试汇总
ruff: passed
mypy strict: 100 source files passed
pytest (not eval, database enabled): 58 passed
Alembic 0013 downgrade/upgrade: passed
真实模型 eval: not run
HarmonyOS build/E2E: not run
```

当前仍存在的 P0/P1：未来外部 Tool 下游幂等契约、真实 Push 的持久幂等验证、无法强制终止的 parser thread、实际 Embedding 服务配置、Memory 通用候选抽取/矛盾检测、Source 页码 provenance/OCR/semantic retrieval。

## 2026-08-25 外部参考与可靠性增量

本批次额外核对 LangGraph、OpenAI Agents SDK、AutoGen、LlamaIndex/Llama Agents、Dify、PostgreSQL、Celery、SQLAlchemy 与 Unstructured 的官方资料/官方仓库，记录见 `docs/research/agent-runtime-reference-research-2026-08-25.md`。采用数据库扫描 + 原子 claim、at-least-once + 显式幂等、Source 持久状态机；未照搬多 Agent、Redis/Celery/Temporal 等重型结构。

Agent Graph 的两条 `ainvoke` 路径现均显式设置 `durability="sync"`。服务生命周期启动 `RunDispatchScanner` 和 `SourceProcessingScheduler`；停止顺序先停止业务 scheduler，再停止 dispatcher/checkpointer。专项测试证明重复扫描不会绕过 Run claim，Source 并发领取互斥、过期接管成功、旧 owner 结果拒绝。
