# Agent Runtime、持久任务与 Source Pipeline 外部参考（2026-08-25）

## 调研范围

本记录服务于当前后端可靠性批次。资料优先级为官方文档、项目官方仓库和成熟开源项目的实际代码；博客和二手教程不作为实现依据。

已核对：

- LangGraph 官方文档与官方仓库：checkpoint、pending writes、durability、interrupt、Store 与长期记忆边界。
- OpenAI Agents SDK 官方文档：HITL、可序列化 RunState、session、长运行 durable integration。
- Microsoft AutoGen 官方文档：Memory protocol、context injection、save/load state、termination / max tool iteration。
- LlamaIndex / Llama Agents 官方仓库：event-driven workflow、持久化、HITL、Source ingestion / retrieval 分层。
- Dify 官方仓库：API、持久 Run、事件流、队列 Worker、resume queue 的部署边界。
- PostgreSQL 官方文档：`FOR UPDATE SKIP LOCKED` 的 queue-like 多消费者适用范围。
- Celery 官方文档：late acknowledgement、worker lost redelivery 与任务幂等之间的约束。
- Unstructured、SQLAlchemy 官方资料用于 Source parsing 和 async transaction 边界核验。

## 对本项目直接有效的结论

### 1. Run、Thread、checkpoint 必须保持不同生命周期

LangGraph checkpoint 使用 `thread_id` 标识一次可恢复执行历史；Store 承担跨 thread 长期数据。项目继续使用业务 Thread 保存对话、Run ID 作为 checkpoint `thread_id`、Memory 保存跨 Thread 长期信息。这样比把三者合并为一个会话对象更符合现有领域设计。

### 2. 恢复是 at-least-once，副作用必须显式幂等

LangGraph 官方说明 interrupt resume 会从节点开头重新执行，interrupt 前的副作用必须幂等。Celery 对 worker-lost redelivery 也给出同样约束。因此继续保留：

- Tool execution ledger 记录副作用结果；
- Application idempotency key 约束业务写入；
- Worker lease 只决定执行所有权，不宣称 exactly-once；
- checkpoint 与业务事务不伪装成一个跨系统原子事务。

### 3. 数据库驱动扫描 + 原子 claim 适合当前规模

PostgreSQL 官方明确指出 `SKIP LOCKED` 不适合一般一致性查询，但适合多个消费者访问 queue-like 表。当前阶段使用 PostgreSQL 持久状态、周期扫描、`FOR UPDATE SKIP LOCKED` / 条件 UPDATE、lease/heartbeat 即可；暂不为了规模假设引入 Redis、Celery、Temporal 或 Dify 式独立队列集群。

### 4. API dispatch 只能是低延迟提示，不能是唯一唤醒来源

Dify 等成熟项目把请求进程、持久 Run、事件流和执行 Worker 分离。项目保留请求后的本地快速 dispatch，但增加数据库扫描器作为可靠唤醒来源。多实例重复唤醒允许发生，真正执行权由数据库 Run claim 决定。

### 5. Source ingestion 应拆为持久状态机

成熟 RAG / Source 系统一般区分上传对象、解析、索引和检索。项目第一版采用：

`Upload -> immutable object/hash -> PENDING row -> leased parser worker -> extracted text/status -> bounded Agent context`

解析 Worker 崩溃后 lease 到期可接管；可恢复基础设施错误使用退避重试；确定性坏文件进入终态失败。OCR、Office、图片理解和 STT 以后作为 parser adapter 增加，不进入 Domain。

### 6. Context 必须有检索与预算

AutoGen Memory protocol 和 LlamaIndex RAG 都把 retrieval 与 context update 分开。项目保持 PROFILE 精确读取、SEMANTIC/EPISODIC top-k、Source 数量/字符预算；不把所有 Memory、Source 或整段 checkpoint 无限制塞给模型。

### 7. 不照搬多 Agent 和重型编排

AutoGen、Dify、Llama Agents 提供多 Agent / workflow 能力，但本项目 v1.0 的单 Executive Agent 足以承载当前主链。只有独立多步自主任务出现明确需求时才增加 Specialist Subgraph。

## 本批次实现决策

- 新增周期性 Run scanner，调用 Application recovery/dispatch 用例；scanner 不直接访问 Repository。
- Source 上传只提交 PENDING；新增 Source claim、lease、heartbeat、attempt、next retry 状态。
- Source Worker 只调用 Application；对象存储和 parser 仍是 Infrastructure ports。
- 使用有上限的指数退避和最大尝试次数；完成/失败写入必须校验 claim owner。
- 继续使用 PostgreSQL 作为权威协调存储，不新增外部 broker。
- LangGraph 运行调用显式采用同步 durability，并针对当前安装的 `langgraph 1.2.11` 做 checkpoint/recovery 测试；同时关注官方仓库已披露的 durability ordering 修复历史。

## 主要官方入口

- LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph interrupts: https://docs.langchain.com/oss/python/langgraph/interrupts
- LangGraph repository: https://github.com/langchain-ai/langgraph
- OpenAI Agents SDK HITL: https://openai.github.io/openai-agents-python/human_in_the_loop/
- OpenAI Agents durable integrations: https://openai.github.io/openai-agents-python/running_agents/
- AutoGen Memory/RAG: https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/memory.html
- LlamaIndex repository: https://github.com/run-llama/llama_index
- Llama Agents repository: https://github.com/run-llama/llama-agents
- Dify repository: https://github.com/langgenius/dify
- PostgreSQL locking clause: https://www.postgresql.org/docs/current/sql-select.html
- Celery tasks guide: https://docs.celeryq.dev/en/stable/userguide/tasks.html
- SQLAlchemy SELECT / locking API: https://docs.sqlalchemy.org/en/20/core/selectable.html
- Unstructured partitioning: https://docs.unstructured.io/open-source/core-functionality/partitioning

## 风险与复核点

- `SKIP LOCKED` 返回的是不一致视图，只用于领取，不用于用户可见查询或统计真相。
- lease 不能阻止已失联旧 Worker 在外部系统完成副作用；副作用 ledger 和目标系统 idempotency key 仍是必要保护。
- checkpoint 持久化不等于业务数据库提交；跨边界重放必须测试。
- Source parser 需要限制文件大小、页数/耗时和错误文本，避免资源耗尽与敏感路径泄露。
- 成熟项目的架构只能用于验证机制，不应覆盖七份 v1.0 文档定义的 Personal State / Memory / Source / Automation 领域边界。
