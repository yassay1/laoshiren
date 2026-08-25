# Memory 形成重构 —— 开发报告

日期：2026-08-26
范围：把记忆形成从「确定性占位符」修回文档设计的「LLM 驱动 + 后台 Worker」

## 1. 背景与结论

`老实人_Personal_State与Memory数据设计_v1.0.txt` §27-29 早已定义了正确的记忆形成设计：

> Event Buffer → Debounce/Batch → Memory Formation Worker → Memory Manager(LLM)
> → 输出 Profile Update / Semantic Upsert / Episodic Insert / Ignore

而此前的代码实现是 6 个字符串前缀的确定性匹配 + Run 完成后同步热路径——这是上一轮在模型 key 不可用时的权宜占位，**既偏离官方实践（LangMem/LangGraph/MemGPT），也偏离了项目自己的文档基线**。本次把它修回文档设计的形态。

## 2. 分阶段完成内容

### 阶段 1：候选 schema + action 枚举 + 安全闸
- 新增 `application/memories/candidate.py`：
  - `MemoryCandidateAction`：`CREATE / UPDATE / MERGE / SUPERSEDE / IGNORE`（文档 §28）。
  - `MemoryCandidate`：完整候选结构（含 `reason / importance / confidence / thing_id / source_refs / target_memory_id`），带 `__post_init__` 校验（mutation action 必须带 target）。
  - `rejects_state_authority`：确定性安全闸，收窄为最无歧义的状态词（截止日期 / deadline / 任务状态 / thing 状态）。
  - `is_explicit_memory_command`：明确命令检测（文档 §16 立即触发）。

### 阶段 2：MemoryManager + Extractor 接口
- 新增 `application/memories/manager.py`：
  - `MemoryFormationContext`：形成输入（对话 + State 变更摘要 + 已有记忆 + active Thing）。
  - `MemoryExtractor` Protocol：LLM 抽取边界。
  - `MemoryManager.form`：LLM 抽取 → 过滤（IGNORE/置信度/安全闸）→ 确定性执行 action。
  - `_apply`：`CREATE→create`、`UPDATE/MERGE→update`、`SUPERSEDE→supersede+create`。LLM 只判断，落库由代码执行。

### 阶段 3：后台 MemoryFormationWorker
- 新增 `workers/memory.py`：`MemoryFormationEvent` + 内存队列 + `MemoryFormationWorker`（lease 式批量 drain，复用项目 worker 模式）。
- 两条路径：常规入队（后台）+ 明确命令 `process`（立即）。
- 新增 `infrastructure/ai/memory_extractor.py`：`OpenAIMemoryExtractor`（openai 兼容 chat completions，JSON mode，健壮解析）。
- `workers/agent.py` 接线：Run 完成后从 `tool_results` 提取成功动作 → 构造事件 → 明确命令立即触发 / 否则入队。
- 删除 `context.py` 旧确定性形成（`extract_memory_candidate` / 旧 `MemoryCandidate` / `form_from_user_input` / `_profile_key`）。

### 阶段 4：memory 工具补全
- `MemoryManager.remember`：明确命令路径（内容已明确，跳过 LLM 抽取，只做去重 + 落库）。
- `MemoryManager.forget`：用户数据控制（soft delete）。
- `register_memory_tools` 扩展：`memory.remember`（REVERSIBLE_WRITE）+ `memory.forget`（SENSITIVE_WRITE，需 HITL）。

### 阶段 5：Retrieval ranking + Top-K
- `context.py` 新增 `rank_memories`：`importance × type_weight + thing_match 加分`，`EPISODIC` 权重 0.8（文档 §32）。
- `load_context` 增加 `active_thing_ids` 参数。

### 阶段 6：Episodic 形成
- 强化 extractor prompt，明确 episodic 三要素（发生什么 + 结果 + 参考价值）。
- 解析器支持 `EPISODIC` 类型与 `target_memory_id` 的 UUID 归一化。

## 3. 关键设计决策

1. **LLM 只判断，代码只执行**：`MemoryCandidate.action` 由 LLM 输出，落库（create/update/supersede）由 `MemoryManager._apply` 确定性执行，LLM 不直接碰库。
2. **确定性只留安全闸**：`rejects_state_authority` 是唯一 LLM 不可越过的规则（文档 §19 优先级铁律），不再是形成机制。
3. **两条形成路径**：后台批量（常规）+ 明确命令立即（文档 §16）。

## 4. 验证结果

| 检查 | 结果 |
|---|---|
| `ruff check src tests` | ✅ All checks passed |
| `mypy --strict src` | ✅ 109 source files, no issues |
| `pytest`（含集成，`RUN_DATABASE_TESTS=1`） | ✅ 110 passed |

新增测试：候选 schema/安全闸、MemoryManager 各 action、形成 Worker、memory 工具、ranking、extractor 解析。

## 5. 自我反思矫正

1. **安全闸术语收窄**：原「已经完成任务」是整句短语，连续子串匹配不到「我已经完成了这个任务」；且「已完成」歧义大（episodic 也可能说"上次完成了任务"）。收窄为「截止日期/deadline/任务状态/thing 状态」这类无歧义状态词。
2. **frozen DTO 不可原地赋值**：测试 Fake 里对 `MemoryDTO`（frozen dataclass）原地赋值，改用 `dataclasses.replace`。
3. **LLM JSON 的 UUID 归一化**：LLM 返回的 `thing_id/target_memory_id` 是字符串，解析时需 `UUID(str(...))` 转换，否则 `MemoryCandidate` 类型不符。
4. **变量名遮蔽**：`remember` 里 `for memory in existing` 与 `memory = await _apply(...)` 同名导致 mypy 类型冲突，改用 `formed`。

## 6. 尚未完成 / 风险（诚实说明）

1. **真实 LLM 抽取质量未验证**：模型 key 仍是 401。`OpenAIMemoryExtractor` 的 prompt/解析已写好，但真实抽取效果需配 key 后跑 eval。
2. **Active Thing Resolution 未接**：`rank_memories` 支持 `active_thing_ids`，但 worker 尚未解析「当前活跃 Thing」传入（文档 §36）。
3. **形成队列是内存的**：进程重启丢失未处理的形成事件；后台 Worker 不持久（与 Run 队列的持久化恢复是同一性质缺口）。
4. **embedding provider 未配置**：语义检索降级为关键词；`memory.search` 语义能力未实测。
5. **LLM 抽取器与 Executive gateway 共用模型配置**：`MODEL_*` 同时驱动决策与记忆抽取，未支持独立模型。

## 7. 本次边界（明确不做）

- 真实 eval（等 key）。
- procedural memory 演化、多步规划、Specialist Subgraph。
- 客户端、认证、Push。
