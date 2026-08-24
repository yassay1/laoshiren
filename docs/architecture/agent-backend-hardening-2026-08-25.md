# Agent Backend Hardening Report

日期：2026-08-25  
范围：Agent 后端；不包含正式认证、多用户身份体系和前端产品体验。

## 1. 本轮目标

在不改变“单 Executive Agent + Context Engineering + Application Tools + LangGraph Durable Runtime”的前提下，修复旧 Worker 越权落结果、外部 Tool 结果不确定、长对话上下文膨胀、Memory 形成缺少 provenance、Source 类型永久挂起、真实模型评测不可审计等问题。

## 2. 修改前真实状态

- 分支为 `main`，工作树 clean，起始提交为 `70b80ab`；业务 migration head 为 0015。
- 基线重新执行为：ruff 通过，mypy strict（106 个 source files）通过，PostgreSQL/pgvector 测试 64 passed。
- 已有 Thread/Message/Run、Executive 多步 Tool、HITL、Postgres checkpoint、Run lease/recovery、持久 SSE、Tool ledger、Memory/Source/Automation 主链。
- 真实缺口：lease 只校验 worker_id；非 replay-safe Tool 超时仍缺 UNKNOWN 语义；模型上下文缺统一预算；Memory formation provenance 和近似去重不足；DOCX 未解析且其他 unsupported 类型永久 PENDING；真实 eval 仅一个不完整 smoke；无 CI workflow；checkpoint 无清理入口。
- `CLAUDE.md` 不存在；README 和 `docs/CURRENT_IMPLEMENTATION.md` 部分描述落后于真实代码，因此本报告以代码、migration 和重跑结果为准。

## 3. 阅读的项目内部资料

- 根目录 `AGENTS.md`、`README.md`、`.gitignore`、规划与实现审计记录。
- `docs/` 下七份 v1.0 核心设计文档、ADR、当前实现说明和既有开发报告。
- `backend/src`、`backend/tests`、`backend/evals`、Alembic 0001–0015、`pyproject.toml`、`uv.lock`。
- `contracts/` 的 API/SSE 契约，`deploy/compose.yaml`，HarmonyOS Chat/HITL 联调代码。

## 4. 参考的官方资料

| 官方资料 | 来源 | 支持的设计判断 |
|---|---|---|
| LangGraph Persistence | https://docs.langchain.com/oss/python/langgraph/persistence | checkpoint 是 Graph 执行状态；pending writes 和 super-step 恢复不能替代业务副作用幂等。 |
| LangGraph Interrupts | https://docs.langchain.com/oss/python/langgraph/interrupts | resume 会重新进入 interrupt 所在 node；interrupt 前的副作用必须可重放。 |
| Thinking in LangGraph | https://docs.langchain.com/oss/python/langgraph/thinking-in-langgraph | 可重试错误、用户可修正错误、未知错误应采用不同状态处理；Graph 保持 orchestration 职责。 |
| LangGraph Memory / short-term memory | https://docs.langchain.com/oss/python/langgraph/add-memory | thread-scoped 短期状态与跨 thread 长期记忆应分离；模型上下文可裁剪，但不应删除业务消息历史。 |
| langgraph-checkpoint-postgres README | https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/README.md | PostgresSaver 首次需要 setup；checkpoint 反序列化应启用 strict msgpack 或显式 allow-list。 |
| LangGraph msgpack security advisory | https://github.com/langchain-ai/langgraph/security/advisories/GHSA-g48c-2wqr-h844 | `allowed_msgpack_modules=None` 只允许内置安全集合，是当前本地版本可验证的严格配置。 |
| PostgreSQL SELECT / locking | https://www.postgresql.org/docs/current/sql-select.html | `FOR UPDATE SKIP LOCKED` 适合多个消费者原子领取 queue-like rows，但仍需 fencing 防止迟到写。 |
| PostgreSQL Explicit Locking | https://www.postgresql.org/docs/current/explicit-locking.html | row lock 只保护持锁事务，不能保护 lease 过期后的进程外执行结果。 |
| LangMem | https://github.com/langchain-ai/langmem | 长期记忆应提取、合并和更新，并可选择 hot path 或 background formation。 |
| LangGraph memory-agent | https://github.com/langchain-ai/memory-agent | user-scoped 跨 thread Memory 与独立 evaluation set 是成熟参考；本项目保留自有 Domain/Application 数据模型，不引入其部署模板。 |

上述资料用于验证设计判断；没有机械替换现有 Application、Repository 或 Graph。

## 5. Gap Analysis

| Gap | 判断 | 本轮结果 |
|---|---|---|
| Worker A lease 过期后迟到写 | P0，真实并发风险 | Run 与 Tool 都增加每次 claim 唯一 token；所有 owner-owned 更新执行 CAS。 |
| 外部 Tool timeout 后真实结果未知 | P0，不可自动当 FAILED 重试 | 新增 UNKNOWN；non-replay-safe 过期执行变 UNKNOWN 并中止 Agent。 |
| interrupt 前副作用 | P0 | 逐 node 核验；当前只有 payload/state 构造，无需迁移副作用，并补恢复覆盖。 |
| checkpoint serializer | P0 | 本地 3.1.2 显式使用严格 `JsonPlusSerializer`。 |
| checkpoint 无限增长 | P1 运维风险 | 增加默认 dry-run、显式 `--apply` 的 terminal Run retention 脚本。 |
| 长 Thread prompt 膨胀 | P1 | 新增统一 Context Builder 和总/分区预算。 |
| Memory 什么都记或无 provenance | P1 | 候选、置信度、拒绝 Personal State、去重、PROFILE supersede、Run/Message provenance。 |
| Source 无版本、DOCX 不可用、unsupported 永久 PENDING | P1 | pipeline 版本元数据、DOCX 解析、unsupported 显式 FAILED。 |
| live model 行为不可审计 | P1 | 15 场景 opt-in trajectory harness；本机实际请求暴露 401 凭据问题。 |
| SSE WAITING reconnect 与序号约束测试不足 | P2 | 增加游标去重、单调序号和唯一性断言。 |
| CI 缺失 | 工程可靠性 Gap | 增加 PostgreSQL 17 + pgvector 的 GitHub Actions 质量门。 |

## 6. 实际完成的代码修改

- migration 0016：Run/Tool claim fencing token。
- migration 0017：ToolExecution `UNKNOWN`。
- migration 0018：Memory `provenance_run_id` 与 `source_message_ids`。
- 新 Context Builder；修复消息 Repository `LIMIT` 取到最旧而不是最新消息的真实缺陷。
- Memory candidate/formation、Source DOCX/version/unsupported、真实 eval、checkpoint cleanup、结构化 Agent lifecycle 日志、CI。
- 分阶段提交：`e8e47c0`、`9663a0d`、`76480b4`、`d8a623f`、`dcff5b1`。

## 7. Durable Runtime / Worker 改进

- `agent_runs.claim_token` 每次 claim/takeover 都生成 UUID。heartbeat、WAITING_USER、complete、fail 必须同时匹配 user、owner、claim_token。
- Graph state 和 resume `Command.update` 都携带 token；Tool ledger claim 首先验证当前 Run ownership。
- 即使新旧协程使用完全相同的 worker_id，旧 token 也不能续租或落结果。数据库集成测试覆盖此竞态。
- checkpoint execution key 明确为 Run ID；业务 Thread 继续承载跨 Run 消息历史。一个 Run 的 resume 使用同一个 Run ID checkpoint，后续新 Run 不继承旧 Graph state。
- `PostgresCheckpointLifecycle` 显式传入严格 serializer，并继续调用官方 `setup()`。
- `scripts/cleanup_checkpoints.py` 按旧 terminal Run 批量找候选；默认只报告，只有 `--apply` 删除对应 Run ID 的 checkpoint thread，避免请求链自动删调试数据。

## 8. Tool / Idempotency 改进

- ledger row 不存在即 `NOT_STARTED`；持久状态只保存 `RUNNING/SUCCEEDED/FAILED/UNKNOWN`。
- 每次 Tool claim 也有独立 claim_token，完成更新为 owner + token CAS。
- replay-safe Tool 的过期 RUNNING 可接管；non-replay-safe Tool 过期后原子转 UNKNOWN，不自动重放副作用。
- 稳定 idempotency key 继续由 `run_id + action_id` 语义导出，Application 的业务幂等仍是最终防线。
- `UNKNOWN` 会产生 `TOOL_OUTCOME_UNKNOWN`，Agent 不得声称成功；未来外部 Provider 可直接复用 ledger 提供的稳定 key。

## 9. Context Engineering 改进

`AgentContextBuilder` 使用 24,000 字符总预算：recent messages 8,000/最多 20 条、old summary 3,000、Memory 5,000、Source 8,000，并按 PROFILE、相关 Memory、证据的价值顺序组装。

- 短 Thread 不生成 summary。
- 长 Thread 生成有界提取式 summary，仍保留最近消息。
- Tool/HITL 当前 Run 的恢复依靠 checkpoint，不靠裁剪后的旧聊天重建。
- 原始 Message 永久保存在业务库；压缩只影响一次模型输入。
- Gateway 不再自行二次截断 `[-20:]`，避免两套预算冲突。

当前 summary 是确定性的提取式摘要，不是持久 LLM summary；优点是无额外模型调用且可测试，缺点是超长复杂对话的信息压缩质量仍有限。

## 10. Memory Formation 改进

执行链：`completed Run -> deterministic candidate extraction -> normalize -> confidence gate -> exact/near dedup -> PROFILE conflict/supersede -> persistence`。

- Candidate 包含 type、content、confidence、profile_key、run_id、source_message_ids。
- 显式“请记住”、偏好和回复风格可形成长期 Memory；任务状态、Thing 状态、Deadline 等 Personal State 权威数据被拒绝。
- PROFILE 使用 exact key；新事实通过既有 version/supersede 链覆盖旧值。
- Semantic 候选先 exact，再以归一文本相似度做近似去重；幂等 key 包含 Run 和候选 hash。
- 形成发生在 Run 完成落库后；形成失败记录结构化异常，不会把已经成功的回复改成 FAILED。
- Agent 运行前仍执行 PROFILE exact load、semantic/episodic top-k retrieval；配置 embedding 时使用 pgvector，未配置时词法降级。

限制：本轮没有引入 LLM 自动抽取器或独立 durable memory queue。当前 formation 覆盖明确指令和高置信规则，不能宣称能从任意自然语言自动学习所有长期事实。

## 11. Source / Evidence 改进

- 上传继续持久化 content hash、object key、MIME、size 和 idempotency key。
- Source metadata 新增 parser、chunk、embedding model/version；chunk metadata 同步保存版本。
- TXT、Markdown、文本 PDF 保持原实现；DOCX 使用有解压大小限制的 ZIP + `document.xml` XML 提取，保留段落边界。
- PDF chunk 保持 page provenance；所有检索 chunk 保持 source_id、chunk_id、ordinal、page、char range。
- 同一个 READY Source 的重复 complete 会 CAS 失败，不插入重复 chunk；`(source_id, ordinal)` 仍有数据库唯一约束。
- 图片、PPT、音频等没有可靠 parser 的类型仍可保留原文件，但立即标记 `FAILED/SOURCE_TYPE_UNSUPPORTED`，不再假装成功或永久占用 backlog。
- OCR、图片理解、STT 没有伪实现；未来通过既有 `SourceParser` port 接入。

限制：Source 当前是 immutable upload；尚无“替换原文件并重建同一 source_id”的 reprocess API。更新使用新 Source/idempotency key，旧 Source provenance 不被暗中改写。

## 12. Real-model Eval / Smoke Test

`backend/evals` 现在定义 15 个场景：直接回答、创建 Thing、创建/完成 Task、多 Tool、clarification、HITL、Tool failure、Memory write、PROFILE update、跨 Thread recall、Source evidence/no-evidence、Automation、长 Thread、模糊语言。

运行方式：

```powershell
$env:RUN_MODEL_EVALS='1'
$env:MODEL_EVAL_SCENARIOS='direct_answer' # 或 all / 逗号分隔 key
uv run pytest evals/test_live_agent_scenarios.py -q -s
```

每条记录 final answer、tool/event trajectory、arguments/results（事件提供时）、interrupt、run status、latency、token_usage。Provider 当前没有返回 usage，字段明确为 null；不绑定 LangSmith SaaS。

本机实际结果：环境检测到 DeepSeek 配置并发送了请求，但 Provider 返回 HTTP 401。测试为 failed，不是 skipped；Run 失败状态正确落库。随后 Worker 映射改为保留 `MODEL_AUTH_FAILED`。由于凭据不可用，本轮不能宣称真实模型 smoke 通过。

## 13. SSE / Automation / Observability

- SSE 数据仍由持久 `run_events` replay；新增 WAITING_USER 后使用 Last-Event-ID 不重复 interrupt 的测试。
- 完成 Run 后事件 sequence 严格递增且 `(run_id, sequence)` 唯一；completed reconnect 只补发游标后的终态。
- Agent Worker 在 claim、complete、fail 写结构化日志 correlation：run_id、thread_id、user_id、worker_id、attempt/error code。
- Tool、HITL、Memory formation、Source retrieval 都可由 Run ID 联结事件、checkpoint state 或 provenance；Automation 保持 Occurrence/Outbox durable 链。
- Automation/Outbox 本轮审计后保留：`SKIP LOCKED` claim、occurrence 唯一键、retry/exhaustion、lease takeover 的现有实现和测试，没有为“改动”而重写。

## 14. 数据库 Migration

当前 head：`20260825_0018`。

- 0016：`agent_runs.claim_token`、`tool_executions.claim_token`。
- 0017：`tool_execution_status` 增加 UNKNOWN；downgrade 明确把 UNKNOWN 映射 FAILED 后重建 enum。
- 0018：`long_term_memories.provenance_run_id`、`source_message_ids UUID[]`。

实际执行 `0018 -> 0015 -> 0018` 成功。没有新建独立向量库，仍使用 PostgreSQL/pgvector。

## 15. 新增/修改文件

关键位置：

- `application/context.py` — `AgentContextBuilder.build`：统一模型上下文预算。
- `workers/agent.py` — `AgentRunWorker.run_once`：claim fencing、context、resume、formation、日志。
- `application/runtime/service.py` — Run/Tool ownership、UNKNOWN 和事件用例。
- `infrastructure/persistence/repositories/runtime.py` — PostgreSQL CAS、claim/takeover。
- `infrastructure/persistence/checkpoints.py` — strict serializer/lifecycle。
- `application/memories/context.py` — candidate extraction、validation、dedup、formation。
- `application/sources/service.py` — ingestion 状态、版本、chunk/evidence。
- `infrastructure/sources/text_parser.py` — TXT/Markdown/PDF/DOCX parser。
- `evals/scenarios.py`、`evals/test_live_agent_scenarios.py` — 可选真实模型轨迹评测。
- `scripts/cleanup_checkpoints.py` — checkpoint retention 运维入口。
- `.github/workflows/backend.yml` — PostgreSQL/pgvector CI 质量门。
- migrations 0016–0018，以及对应 unit/integration/API/worker tests。

## 16. 测试结果

最终复核实际结果：

- `uv run ruff check src tests evals scripts`：passed。
- `uv run mypy --strict src`：passed（105 source files，eval harness 独立于生产包）。
- `RUN_DATABASE_TESTS=1 uv run pytest -q`：73 passed（4.68s）。
- PostgreSQL/pgvector：包含在上述 73 项中，passed。
- migration：0015→0018 往返 passed，head 0018。
- checkpoint cleanup dry-run：passed，0 个超过 30 天的候选。
- real-model smoke：failed；DeepSeek HTTP 401 / credentials rejected。
- GitHub Actions：workflow 已新增，但尚未在远端 runner 执行（本轮未 push）。

## 17. 尚未完成事项

- 正式认证/多用户身份体系按范围明确不做。
- DeepSeek 有效凭据需要人工更新后重跑 15 场景；当前只有确定性 Fake Gateway 测试和一次真实失败证据。
- Memory formation 不是通用 LLM extractor，也不是独立 durable 后台队列。
- embedding key/model 未配置，生产语义召回的真实 provider smoke 未执行；pgvector repository 用确定性向量通过。
- Source replacement/reprocess API、OCR、图片理解、Office PPT、STT 未实现。
- checkpoint cleanup 是显式运维命令，尚未加入生产定时任务；event retention 也尚无自动清理策略。
- Notification Adapter 仍是 recording 开发实现，不能宣称真实 Push 已送达。
- CI workflow 尚待 push 后由 GitHub runner 首次验证。

## 18. 当前 Agent 能力最终结论

当前 Agent 后端已构建成可运行、可持久暂停/恢复、具备多步 Application Tool、并发 fencing、Tool replay/UNKNOWN、受预算 Context、长期 Memory 召回与有限形成、Source Evidence、Automation durable worker、SSE replay 的单 Executive Agent 系统。确定性业务和 PostgreSQL/pgvector 主链通过 73 项测试，migration 可往返。

可以宣称：后端 Agent 架构和确定性执行链构建成功，核心业务功能不依赖正式用户认证即可联调。

不能宣称：真实 DeepSeek 模型已验证成功、任意自然语言记忆都能自动形成、外部副作用 Provider exactly-once、所有文件多模态解析、生产 Push/认证已经完成。

### 建议人工聊天验证

按顺序发送，保留同一 Thread 或按说明新建 Thread：

1. `用两句话告诉我你现在能帮我做什么。`
2. `创建一个事项：九月搬家。`
3. `在九月搬家里创建任务：联系三家搬家公司，截止到本周五。`
4. `再创建任务：整理需要搬走的家具；然后把联系搬家公司标记为 blocker。`
5. `把联系搬家公司标记完成，并告诉我九月搬家还剩哪些任务。`
6. `请记住：我选择服务商时更重视可靠性，不追求最低价。`
7. 新建 Thread：`我选择搬家公司时最重视什么？`
8. 上传 TXT/Markdown/PDF/DOCX 后发送：`只根据这份文件，告诉我截止日期，并指出证据所在页或片段；没有证据就明确说没有。`
9. `删除九月搬家这个事项。` —— 应进入 HITL；先拒绝一次，再重试并确认。
10. 在 WAITING_USER 时断开 SSE、重启服务、重新连接并提交确认，验证同一个 Run resume。
11. `每天早上 8 点提醒我查看今天最重要的任务。`
12. `完成任务 ID 00000000-0000-0000-0000-000000000099。` —— 不得声称成功。
13. `那个重要的事情下周差不多弄一下。` —— 应澄清，而不是编造 Thing/deadline。
14. 连续发送 30 条带编号说明，再问：`总结旧要求，同时逐字复述最近三条。` —— 验证长 Thread 的 recent 保留。
15. 测试期间强制停止 Worker，等待 lease 过期后重启；Run 应被接管，旧 Worker 结果不能覆盖新 owner。
