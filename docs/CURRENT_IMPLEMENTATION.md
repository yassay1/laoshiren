# 当前实现与审核说明

更新时间：2026-08-24。本文件只描述仓库当前代码，不把七份 v1.0 设计目标误写成已完成功能。

## 1. 实际组成

- HarmonyOS：可编译安装的单 entry Stage Model 应用；Chat 已接后端，其他三个一级页面主要是展示壳。
- Backend：Clean Architecture 风格模块化单体，业务域包含 Personal State、Source、Memory、Automation/Attention、Runtime。
- Agent：单一 Executive LangGraph，支持 respond、ask_user、Tool、确定性 Policy、敏感操作 interrupt/resume。
- Persistence：PostgreSQL/pgvector 业务表 + LangGraph 独立 checkpoint 表；Source 原件使用本地文件适配器。
- Contracts：OpenAPI 快照和 SSE 事件 Schema。

## 2. 后端入口和依赖组装

- `backend/src/laoshiren/__main__.py::main`：Windows 正式开发入口；显式创建 SelectorEventLoop 后启动 Uvicorn。
- `backend/src/laoshiren/main.py::create_app`：创建 FastAPI、注册中间件/路由/异常处理；lifespan 启停 checkpoint、Agent Worker dispatcher 和数据库。
- `backend/src/laoshiren/bootstrap.py::bootstrap`：组装 Database、各 Application Service、本地对象存储、Recording Notification Adapter、Checkpoint 和进程内队列。
- `backend/src/laoshiren/bootstrap.py::build_configured_agent_worker`：按环境选择 DeepSeek 或智谱 Gateway，注册 Personal State Tools，编译 Graph。

Presentation、Agent Tool 和 Worker 都通过 Application Service；Domain 未导入 FastAPI、SQLAlchemy、LangGraph 或模型 SDK。

## 3. 真实聊天执行链

1. `ChatViewModel.initialize` 调用 `ChatRepository.createThread`。
2. `ApiClient` 携带开发 Bearer Token 和 Idempotency-Key，请求 `POST /api/v1/threads`。
3. FastAPI `runtime.create_thread` 路由调用 `RuntimeApplicationService.create_thread`，经 UoW 保存 Thread。
4. `ChatViewModel.send` 请求 `POST /api/v1/runs`；Application 在同一事务创建 QUEUED AgentRun、USER Message 和 status.updated Event。
5. 提交成功后 `InProcessRunDispatcher.dispatch` 入队；lifespan 启动的 consumer 调用 `AgentRunWorker.run_once`。
6. Worker 把 Run 转为 RUNNING，读取 Thread Messages，以业务 Thread ID 作为 LangGraph checkpoint thread_id。
7. `build_executive_graph` 调用模型 Gateway；模型每轮选择 respond、ask_user 或一个 Tool。
8. Tool 路径依次经过 `ToolPolicy.evaluate`、必要的 LangGraph interrupt、`ToolRegistry.execute` 和具体 Personal State Application 用例。
9. Tool 生命周期由 `RuntimeAgentEventSink` 写成持久 Run Event；Tool 结果回到 Graph，再次交给 Executive 决策。
10. 最终文本由 `RuntimeApplicationService.complete_run` 保存为 ASSISTANT Message，同时写 assistant.message 和 run.completed。
11. HarmonyOS `AgentStreamClient` 消费 SSE；流结束后 `ChatViewModel` GET Run 和 Thread Messages，以数据库最终状态刷新 UI。

## 4. 已实现业务能力

### Personal State

- Thing：创建、查询、搜索/分页、名称/状态/阶段更新。
- Task：创建、状态转换、完成、取消后受控 reopen。
- ThingDate：日期列表、专用 Deadline 设置、certainty/precision、primary projection、乐观锁。
- Blocker：创建、查询、解决。
- ThingRelation：RELATED_TO / DEPENDS_ON / PART_OF。
- StateMutation 与 TimelineEvent：重要写入的审计和现实事件记录。

核心：`PersonalStateApplicationService`、`domain/personal_state/entities.py`、`repositories/personal_state.py`。

### Source

- 流式上传，限制 25 MiB；检查扩展名、MIME、magic bytes。
- 服务端 object key、本地对象存储、SHA-256；DB 只存元数据。
- Source 查询、关联 Thing，关联产生 Mutation/Timeline。
- 尚无 PDF/OCR/STT/Office 文本解析或对象存储云适配器。

核心：`SourceApplicationService`、`LocalObjectStorage`。

### Long-term Memory

- PROFILE / SEMANTIC / EPISODIC；ACTIVE / SUPERSEDED / DELETED。
- 创建、查询、关键词过滤、更新、软删除、版本和幂等 operation。
- PostgreSQL vector(1536) 余弦检索 Repository 路径已有集成测试。
- 没有 Embedding Provider、自动 Memory Formation Worker 或 Agent Retrieval 接入；当前 Graph 不读取 Memory。

核心：`MemoryApplicationService`、`SqlAlchemyMemoryRepository`。

### Automation / Attention

- ONE_SHOT、固定间隔 RECURRING；CONDITION_WATCH 创建即 PAUSED。
- 到期领取、occurrence 去重、Notification Outbox、状态控制和通知查询。
- Attention 从 deadline/blocker 等状态派生并记录 surfaced/acknowledged/dismissed feedback。
- 当前 Notification Adapter 只是内存 Recording Adapter；没有 Push Kit 服务端发送。
- `workers/automation.py::run_once` 存在，但没有生产 scheduler/常驻 worker 启动它。

### Runtime / Agent

- Thread、Message、AgentRun、RunEvent、RunOperation 分离持久化。
- Run 状态：QUEUED / RUNNING / WAITING_USER / COMPLETED / FAILED / CANCELLED。
- SSE 持久事件重放、Last-Event-ID、终态结束；网络断开不取消 Run。
- Executive Graph、PostgreSQL checkpoint、8 个 Personal State Tools、Tool Policy、HITL 基础控制流。
- DeepSeek 和智谱 HTTP Adapter；当前本地 `.env` 选择实际 Provider。

## 5. 数据库

Alembic 0001–0007 建立 users、things、tasks、thing_dates、state_mutations、timeline_events、sources、thing_sources、long_term_memories、memory_operations、blockers、thing_relations、automations、automation_operations、notification_outbox、attention_feedback、threads、agent_runs、messages、run_events、run_operations。

LangGraph 的 checkpoints、checkpoint_writes、checkpoint_blobs 等由 `PostgresCheckpointLifecycle.start/setup` 管理，不属于业务 migration。

## 6. 当前客户端完成度

- `AppShell.ets`：Today / Things / Chat / Me 四栏。
- `ChatPage.ets` + `ChatViewModel.ets`：文本对话、消息气泡、加载、错误重试、等待确认卡片。
- `ChatRepository.ets`：Thread/Run/Message/Resume API。
- `AgentStreamClient.ets`：Network Kit SSE 适配器。
- `ApiClient.ets`：集中 HTTP 请求。

Today、Things、Me 没有接 Product API；无 Thing Detail、Timeline、Source Preview、Automation、Settings 实际流程，无账号、附件、Share、STT、Push、Deep Link、离线缓存。

## 7. 已确认缺陷和风险

1. **HITL 载荷不一致**：Graph confirmation 判断 `response.action == "confirm"`，HarmonyOS 发送 `{approved: boolean}`。当前“确认继续”会被 Graph 当作拒绝。
2. **队列不持久**：`InProcessRunDispatcher` 只在内存；进程崩溃或重启后不会扫描数据库 QUEUED Run。
3. **Graph 无步数上限**：Executive 可反复调用 Tool，没有显式最大循环/预算。
4. **Checkpoint thread 粒度**：所有同一业务 Thread 的 Run 共用 LangGraph thread_id；需要人工验证跨 Run checkpoint 继承是否符合预期。
5. **反序列化白名单**：真实运行出现 LangGraph 未注册枚举类型警告；未来严格 msgpack 版本可能阻断恢复。
6. **认证仅开发态**：固定 token 和固定 user UUID；无正式用户、设备、token 生命周期或权限模型。
7. **客户端配置硬编码**：HTTP base URL 和 `change-me` 在源码；明文网络全局放行只适合本地。
8. **客户端会话不可恢复**：每次 Chat ViewModel 初始化新建 Thread，不读取已有 Thread 或未完成 Run。
9. **重试语义可能重复业务输入**：客户端 retry 使用新 Idempotency-Key 新建 Run，不是重连原 Run。
10. **SSE 解析较窄**：只读取每个 block 第一条 `data:` 行，静默吞掉 JSON 解析错误，没有 Last-Event-ID 重连实现。
11. **Automation 没有生产调度器**，Notification 也未真正发送到 HarmonyOS。
12. **Memory/Source 尚未进入 Agent 上下文**，设计中的 Relevant Prefetch、JIT Retrieval、Perception、Memory Formation 未实现。
13. **API 契约快照可能滞后**：后续任何路由/Schema 改动都需重新生成 `contracts/openapi.json`；当前无 CI 自动校验。
14. **仓库尚无任何 Git commit**：全部有效文件仍是未跟踪状态，无法依靠版本历史审计或回退。

## 8. 文档与设计差异

- 七份 v1.0 文档是目标基线；其中完整多模态、Push、Specialist Subgraph、并行/DAG、Memory Formation、正式 Auth、完整 HarmonyOS 产品页尚未实现。
- Graph 当前只有一个小型循环，不包含设计中的 restore_runtime、Relevant Prefetch、JIT Retrieval、Specialist Subgraph、并行或重规划。
- Source 当前只保存/关联，不执行设计中的理解与证据抽取。
- Automation 当前只生成通知 Outbox，不会触发无用户在线的 Agent Run。
- HarmonyOS 设计要求 Light/Dark、生命周期恢复和平台 Adapter；当前只有颜色资源与基础 UI，恢复能力未完成。

## 9. 测试现状

- Unit：Task/Run 状态机、Executive Graph、Policy/Tool Adapter、两个模型 Gateway、进程内 Dispatcher。
- Integration API：health、Personal State、Source、Memory、Automation/Attention、Runtime。
- Integration persistence/worker：pgvector 排序、checkpoint setup、Application 原子写、Agent Worker 完整落库。
- Evals：DeepSeek 真实模型简单 Run，必须显式开启。
- 缺口：HarmonyOS 自动化测试、真实 HITL 端到端、崩溃恢复、并发/负载、安全、Automation scheduler、Push、Source 解析和模型质量矩阵。
