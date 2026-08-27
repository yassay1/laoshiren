# Search 与并行只读 Tool 技术设计 v1

状态：Draft（待评审）  
日期：2026-08-27  
基线：老实人 Agent 架构 v1.0、Tool/API Policy v1.0、工程目录规范 v1.0  
范围：后端 `search.*` Tool、Executive 并行只读执行（E11 最小闭环）、与 Deadline Policy / CONDITION_WATCH 的衔接  
非范围：HarmonyOS 客户端、正式 Push、calendar.*、通用 Specialist 多 Agent 平台

---

## 1. 问题陈述

### 1.1 产品缺口

| 场景 | PRD/设计 | 当前代码 |
|------|----------|----------|
| 「听说截止改到 22 号」 | 不得未验证覆盖 CONFIRMED deadline；应 `search.official` 或追问 | Policy `REQUIRE_MORE_CONTEXT` 已有，**无外网验证 Tool** |
| 「同时查官网、文件和当前进度」 | E11 并行独立读取后综合 | Graph **每轮仅 1 个 Tool**，顺序执行 |
| 「官网公布结果后告诉我」 | CONDITION_WATCH + search | Automation 类型为 **stub** |
| 比赛/政策类事实 | 优先官方来源排序 | 无 `search.*` |

### 1.2 设计目标

1. **受控外网读取**：Executive 通过 `search.web` / `search.official` 获取可引用证据，禁止模型「假装搜过」。
2. **并行只读（E11）**：单轮内可并行 `state.*` / `memory.*` / `source.*` / `search.*` 的 READ Tool，fan-in 后由 Executive 单次写入。
3. **与现有架构一致**：Application Port → Infrastructure Adapter → Agent Tool；不污染 Domain；组装在 `bootstrap.py`。
4. **可测试、可观测、可计费**：每次搜索落 `ToolExecution`；支持 mock；结果可缓存。

### 1.3 非目标（本设计不做）

- 固定多 Agent / Supervisor-Planner 组织
- 模型内置 browsing（不可审计、难对齐 ToolResult 契约）
- 并行 **写** Personal State（仍由 Executive 单次 mutation）
- 完整网页浏览器自动化（Playwright 等）
- OCR / 图片理解（仍走未来 `perception.*`）

---

## 2. 架构总览

```
Executive Agent
      │
      ├─ respond / ask_user
      │
      └─ call_tool (single) ──────────────┐
          call_tools (batch, READ-only) ──┤
                                          ▼
                                    Tool Registry
                                          ▼
                                    Tool Policy
                          (ALLOW for search.*; P02 linkage)
                                          ▼
                          ┌───────────────┴───────────────┐
                          ▼                               ▼
              SearchApplicationService          PersonalState / Memory / Source
                          ▼                               Services
              WebSearchPort (Infrastructure)
                          ▼
              TavilyAdapter | SerperAdapter | RecordingAdapter(dev)
```

**并行执行位置**：LangGraph `execute` 节点内，对 **同一 decision batch** 的多个 READ Tool 使用 `asyncio.gather`；不新增顶层 Agent。

**写入规则**（Agent 架构 §24）：并行阶段只允许 research/read；`set_deadline` / `archive_thing` 等必须在 fan-in 后的 **下一轮** Executive decision 中单独执行。

---

## 3. Search 子系统

### 3.1 模块边界

```
backend/src/laoshiren/
  application/search/
    ports.py          # WebSearchPort, SearchQuery, SearchHit, SearchResponse
    service.py        # SearchApplicationService
    dto.py            # SearchResultDTO（给 Tool / API）
  infrastructure/search/
    tavily.py         # 默认生产适配器（可配置）
    serper.py         # 可选备选
    recording.py      # 开发/测试：返回 fixture
    cache.py          # 可选：PostgreSQL 或内存 TTL 缓存
  agent/tools.py      # register_search_tools()
```

Domain **不**新增 Search 实体；外网结果是 **瞬态证据**，权威状态仍在 Personal State。需要长期留存时 **可选** 归档为 `Source`（`origin=SYSTEM`）。

### 3.2 Port 契约

```python
@dataclass(frozen=True, slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    published_at: datetime | None
    domain: str
    rank_score: float  # 0..1，adapter 或 service 归一化

@dataclass(frozen=True, slots=True)
class SearchResponse:
    query: str
    provider: str
    retrieved_at: datetime
    hits: tuple[SearchHit, ...]
    cache_key: str | None  # 命中缓存时

class WebSearchPort(Protocol):
    async def search(
        self,
        *,
        query: str,
        limit: int,
        recency_days: int | None,
        include_domains: tuple[str, ...] | None,
        exclude_domains: tuple[str, ...] | None,
    ) -> SearchResponse: ...
```

### 3.3 Application 用例

`SearchApplicationService` 两个对外方法（Tool 调用）：

| 方法 | 说明 |
|------|------|
| `search_web(user_id, query, limit?, recency_days?, domains?)` | 一般公开搜索 |
| `search_official(user_id, query, entity?, official_domains?, limit?)` | 官方优先搜索 |

**`search_official` 与 `search_web` 共用同一 `WebSearchPort`**，差异在 Application 层：

1. **域名约束**：`official_domains` 来自（按优先级）Tool 参数 → Thing.metadata → 用户 Profile Memory 中的 `official_site` → 空则仅做排序不加硬过滤。
2. **排序**：命中 `official_domains` 的 hit `rank_score += 0.3`（上限 1.0）；其余按 provider 分数。
3. **截断**：默认 `limit=5`，snippet 总字符 ≤ `search_max_snippet_characters`（默认 8000）。
4. **缓存**：`cache_key = sha256(normalized_query + domains + mode)`，TTL 默认 6h（可配置）；同一 Run 内重复搜索直接返回缓存（仍记 ToolExecution，标记 `replayed`）。

### 3.4 Infrastructure 适配器选型

| 适配器 | 用途 | 配置项 |
|--------|------|--------|
| **Tavily**（推荐默认） | Agent 向搜索 API，返回 title/url/content | `SEARCH_API_KEY`, `SEARCH_PROVIDER=tavily` |
| **Serper** | Google SERP 代理 | 同上，`SEARCH_PROVIDER=serper` |
| **Recording** | 无 Key 时开发/CI | 返回固定 fixture，与 `RecordingNotificationAdapter` 同模式 |

**不实现**：Executive 直接 `httpx.get`；搜索密钥不进 Agent/客户端。

### 3.5 可选：搜索结果归档为 Source

当 Policy 要求「可溯源」且 hit 将用于 `set_deadline(CONFIRMED)` 时：

1. `SearchApplicationService.archive_hit_as_source(user_id, hit)` → 创建 `Source`：
   - `origin=SYSTEM`, `source_type=OTHER`, `title=hit.title`
   - `metadata`: `{"url", "retrieved_at", "search_query", "evidence_type": "WEB_SNIPPET"}`
   - `extracted_text = hit.snippet`（或 fetch 全文，V1 仅 snippet）
2. ToolResult.`source_refs` 包含新 `source_id`
3. `set_deadline(..., source_id=...)` 与现有 provenance 链路一致

V1 **默认**：仅返回 URL + snippet，**不自动归档**；Executive 显式需要时再归档（或 Policy 强制 CONFIRMED 时必须带 `source_id`）。

### 3.6 Agent Tools

#### `search.web`

```json
{
  "query": "string, required",
  "limit": "integer, 1-10, default 5",
  "recency_days": "integer, optional",
  "domains": ["string"], "optional allowlist"
}
```

- **Risk**: `READ`
- **Replay**: `READ_ONLY`
- **ToolResult.data**:

```json
{
  "query": "...",
  "retrieved_at": "ISO8601",
  "provider": "tavily",
  "items": [
    {
      "title": "...",
      "url": "https://...",
      "snippet": "...",
      "domain": "example.com",
      "published_at": null,
      "rank_score": 0.82
    }
  ]
}
```

- **ToolResult.source_refs**: 各 hit 的 URL（字符串），便于 Executive 引用

#### `search.official`

```json
{
  "query": "string, required",
  "entity": "string, optional, e.g. 华为开发者大赛",
  "official_domains": ["string"], "optional",
  "thing_id": "uuid, optional — 用于从 Thing.metadata 解析官方域",
  "limit": "integer, default 5"
}
```

行为同 §3.3；Prompt 规则：**截止/规则/政策变更优先调用此 Tool**。

### 3.7 Settings 扩展

```python
# config/settings.py 拟新增
search_provider: str = ""           # tavily | serper | recording
search_api_key: str = ""
search_api_base: str = ""           # 可选覆盖
search_timeout_seconds: float = 15.0
search_default_limit: int = 5
search_max_snippet_characters: int = 8_000
search_cache_ttl_seconds: int = 21_600  # 6h
search_max_queries_per_run: int = 6
```

未配置 `search_api_key` 时：`search.*` Tool **注册但 `enabled=False`**，或返回 `FAILED/SEARCH_UNAVAILABLE`（推荐后者 + 明确 message，便于 Eval）。

---

## 4. 并行只读执行（E11）

### 4.1 决策模型扩展

在 `DecisionKind` 增加：

```python
class DecisionKind(StrEnum):
    RESPOND = "respond"
    ASK_USER = "ask_user"
    CALL_TOOL = "call_tool"
    CALL_TOOLS = "call_tools"   # 新增：并行只读批处理
```

`ExecutiveDecision` 扩展：

```python
@dataclass(frozen=True, slots=True)
class ExecutiveDecision:
    kind: DecisionKind
    content: str | None = None
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
  tool_calls: tuple[ToolCallSpec, ...] = ()  # 新增
    prompt: dict[str, Any] | None = None

@dataclass(frozen=True, slots=True)
class ToolCallSpec:
    tool_name: str
    tool_arguments: dict[str, Any]
```

**模型 JSON 示例（并行）**：

```json
{
  "kind": "call_tools",
  "tools": [
    {"tool_name": "state.list_tasks", "tool_arguments": {"thing_id": "..."}},
    {"tool_name": "search.official", "tool_arguments": {"query": "...", "thing_id": "..."}},
    {"tool_name": "source.search_chunks", "tool_arguments": {"source_id": "...", "query": "deadline"}}
  ]
}
```

**向后兼容**：保留 `call_tool` 单工具；gateway 解析两种形态。

### 4.2 并行安全规则（代码强制，不只靠 Prompt）

`ParallelToolPolicy`（新模块 `agent/parallel.py` 或 `agent/policy.py` 内）在 `execute` 前校验 batch：

| 规则 | 行为 |
|------|------|
| batch 大小 | `1 ≤ len ≤ parallel_read_max`（默认 **4**） |
| 工具类型 | 全部为 `ToolRisk.READ` |
| 禁止组合 | batch 内不得含 `SENSITIVE_WRITE` / `IRREVERSIBLE` |
| 写工具 | 不得出现在 `call_tools` |
| 重复 | 相同 `(name, canonical_args)` 去重 |
| 预算 | 本 Run 已用 `tool_call_count + len(batch) ≤ max_tool_calls`（现有 8） |
| 搜索配额 | batch 内 `search.*` 数量 ≤ 2；全 Run `search.*` ≤ `search_max_queries_per_run`（6） |

校验失败 → 不向外部执行；返回合成 `ToolResult` `FAILED/PARALLEL_BATCH_INVALID` 给 Executive。

### 4.3 Graph 执行流程

```
executive
  → route = call_tool | call_tools | respond | ask_user
call_tools (新节点，或 policy 分支)
  → ParallelToolPolicy.validate(batch)
  → 对每个 spec 顺序过 ToolPolicy（ALLOW/DENY）
  → asyncio.gather(execute_one(spec) for spec in batch)
  → tool_results.extend([...])  # 保持顺序与 action_id 稳定
  → route = executive
```

**action_id 生成**（与现有一致）：

```
action_id = uuid5(ACTION_NAMESPACE, f"{run_id}:{batch_index}:{tool_name}:{index_in_batch}")
```

每个并行 Tool 仍走 **ToolExecutionLedger**（独立 claim/complete）。

### 4.4 与 LangGraph Send / Subgraph 的边界

| 能力 | 本设计（V1） | 后续（V2） |
|------|-------------|-----------|
| 固定 2–4 个已知 READ Tool | `call_tools` + gather | — |
| 动态 N 个子任务（比较 4 个比赛） | 不实现 | `Send` map-reduce + Research Subgraph |
| 子任务内多步推理 | 不实现 | Specialist as Tool |

参考 LangGraph [parallel execution](https://docs.langchain.com/oss/python/langgraph/use-graph-api)；V1 不改 Graph 拓扑，只扩展 execute。

### 4.5 Executive Prompt 补充

在 `agent/prompts.py` 增加：

```markdown
## 并行只读
- 当需要同时读取 State、Memory、Source、外网时，使用 kind=call_tools，一次最多 4 个只读 Tool。
- 并行阶段不得包含 set_deadline、archive_thing、automation.create 等写操作。
- 综合 tool_results 后再决定写入。

## 外网搜索
- 截止/规则/政策/版本变更 → 优先 search.official。
- 一般背景知识 → search.web。
- 搜索失败时如实说明，不得编造官方结论。
- 要用 CONFIRMED 覆盖 deadline，需 search.official 或用户 Source 证据，或用户明确确认。
```

### 4.6 预算与延迟

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `parallel_read_max` | 4 | 单批最大并行读 |
| `max_tool_calls` | 8 | 每 Run 总 Tool 次数（含并行 batch 内每一个） |
| `max_decisions` | 12 | Executive 轮次 |
| `search_timeout_seconds` | 15 | 单次搜索 API 超时 |
| 并行 wall time | ≈ max(各 Tool 延迟) | 非相加 |

---

## 5. Policy 联动（P02 与搜索）

### 5.1 现有 P02（已实现）

无 `source_id` 的 CONFIRMED primary `set_deadline` → `REQUIRE_MORE_CONTEXT`。

### 5.2 本设计新增规则

| 条件 | Policy 决策 | code |
|------|-------------|------|
| `set_deadline` + CONFIRMED + 无 source_id + 本 Run **无** 成功 `search.official` | `REQUIRE_MORE_CONTEXT` | `DEADLINE_NEEDS_VERIFICATION` |
| `set_deadline` + CONFIRMED + 有 source_id | `ALLOW`（已有） | `SOURCE_VERIFIED_DEADLINE` |
| `set_deadline` + CONFIRMED + 本 Run 有 `search.official` SUCCESS 且 arguments 含 `evidence_urls` | `ALLOW` 或 `REQUIRE_CONFIRMATION`（覆盖已有 deadline 时） | `SEARCH_VERIFIED_DEADLINE` |
| `search.*` | `ALLOW` | `ALLOWED` |
| Run 内搜索次数超限 | `DENY` | `SEARCH_QUOTA_EXCEEDED` |

**`evidence_urls`**：`set_deadline` Tool 可选参数，字符串数组；Policy 校验其中至少一个 URL 出现在本 Run 的 `search.official` ToolResult 中。

### 5.3 Executive 行为链（设计文档 §39 示例）

```
用户：「老师刚说比赛可能延期到22号，查一下，顺便看还有什么没完成」

Executive → call_tools:
  - search.official(query="比赛 延期 22号", thing_id=...)
  - state.list_tasks(thing_id=...)

fan-in → Executive 综合
  → 若官方确认：call_tool set_deadline(..., evidence_urls=[...])  # 可能 REQUIRE_CONFIRMATION
  → respond：官方结论 + 未完成任务列表
```

---

## 6. CONDITION_WATCH 衔接（Phase 2，接口预留）

本设计为 Automation 预留，**实现可晚于 search Tool**：

```
CONDITION_WATCH (ACTIVE)
  → Scheduler tick
  → ConditionEvaluator.evaluate(automation)
       → SearchApplicationService.search_official(frozen_query, official_domains)
       → 与 last_snapshot 比较（存 automation.metadata）
  → 若 condition_met：
       → 已有 create_automation_run + NotificationOutbox
  → 若 not met：静默结束
```

`ConditionEvaluator` 放 `application/automations/`，**不**进 Agent Graph。满足条件后的 **解释与 State 写入** 仍交给 Executive Run。

---

## 7. Specialist / Research Subgraph（V2 占位）

**触发条件**（Agent 架构 §25，全部满足才做）：

- 子任务 ≥ 3 且彼此独立（如多比赛对比）
- 每个子任务需 ≥ 3 次 Tool 调用
- 需要独立 context，输出可压缩为一个 JSON

**形态**：

```
Executive → call_tool research.competition_summary
              → Subgraph (internal: search.official × N, extract, summarize)
              → compressed ToolResult
         → Executive synthesis
```

V1 **不实现** `research.*`；E11 用 `call_tools` 覆盖「同时查 progress + 官网 + 文件」。

---

## 8. 可观测性与流式事件

- 每个并行 Tool 仍发 `tool.started` / `tool.completed` SSE（现有 `AgentEventSink`）。
- `call_tools` batch 可选发 `tool.batch_started` / `tool.batch_completed`（`contracts/agent-stream-events` 增量，非破坏性）。
- `ToolExecution` 表已有记录；搜索增加 `arguments` 中 `query` 摘要（不落全文到日志若含 PII）。

---

## 9. 测试策略

### 9.1 单元

- `SearchApplicationService`：official 排序、domain 过滤、缓存命中
- `ParallelToolPolicy`：非法 batch（含写工具、超限、重复）
- `policy.py`：P02 + search evidence 矩阵
- `TavilyAdapter`：httpx mock

### 9.2 集成（`RUN_DATABASE_TESTS=1`）

- `search.web` / `search.official` Tool → Application → RecordingAdapter
- 并行 batch：gather 3 个 READ，结果顺序稳定，ledger 3 条
- E11 eval：`call_tools` gateway 确定性测试
- E03 扩展：搜索后 `set_deadline` 带 `evidence_urls`

### 9.3 Live eval（`RUN_MODEL_EVALS=1`）

- 场景 `parallel_research`：「查官网截止并告诉我未完成任务」
- 需 `SEARCH_API_KEY` + `MODEL_API_KEY`

---

## 10. 实施阶段

### Phase S1 — Search 基础设施（约 1 周）

- [ ] `application/search/*` + `infrastructure/search/recording.py`
- [ ] `register_search_tools()` + `bootstrap` 注入
- [ ] Settings + `.env.example`
- [ ] 单元/集成测试；`search.*` 未配置时优雅失败
- [ ] Prompt 规则（搜索优先 official）
- [ ] **不**改 Graph 并行

**验收**：顺序调用 `search.official` 返回结构化 hits；Eval 可 mock。

### Phase S2 — Tavily 生产适配器 + Policy（约 3–5 天）

- [ ] `infrastructure/search/tavily.py`
- [ ] Policy `evidence_urls` 与 P02 联动
- [ ] 可选 `archive_hit_as_source`
- [ ] Live eval 1–2 条

**验收**：真实 API 能验证「延期到 22 号」类查询（人工抽检）。

### Phase S3 — 并行只读 `call_tools`（约 1 周）

- [ ] `DecisionKind.CALL_TOOLS` + gateway 解析（deepseek + zhipu）
- [ ] `agent/parallel.py` + Graph `call_tools` 节点
- [ ] Prompt 更新
- [ ] E11 确定性集成测试

**验收**：单 Run 内 3 个 READ 并行，wall time < 顺序之和；无并行写。

### Phase S4 — CONDITION_WATCH（约 1 周，可选）

- [ ] `ConditionEvaluator` + Scheduler 钩子
- [ ] Automation metadata `last_search_snapshot`
- [ ] 集成测试：条件满足触发 Agent Run

---

## 11. 风险与对策

| 风险 | 对策 |
|------|------|
| 搜索 API 费用 | 缓存、每 Run 配额、默认 limit=5 |
| 搜索结果不可信 | official 排序 + Policy 不单独凭 snippet CONFIRMED |
| 并行 Tool 某一支失败 | `gather(..., return_exceptions=True)` → 失败项 `FAILED` 入 tool_results，Executive 决定重试或追问 |
| 模型不输出 `call_tools` | 保留单 `call_tool`；Prompt + live eval；必要时 gateway 后处理「建议并行」 |
| 与 checkpoint resume 冲突 | 并行 batch 在单 superstep 内完成；resume 重放整 node（LangGraph 语义）；READ Tool 可重放 |
| 合规/隐私 | 搜索 query 可能含用户事务名；日志脱敏；隐私政策披露「使用第三方搜索」 |

---

## 12. 与成熟项目的对照

| 参考 | 采纳 | 不采纳 |
|------|------|--------|
| LangGraph parallel edges / gather | V1 在 execute 内 gather | 过早 Send map-reduce |
| OpenAI Agents parallel tool_calls | `call_tools` 决策形态 | 整套 Agents SDK runtime |
| Tavily / Serper Agent API | Infrastructure adapter | 模型内置 browsing |
| Perplexity 式 cite | ToolResult hits 带 url/snippet | 把 cite 隐藏进 prose |
| Dify 知识库检索 | Source chunk 已有；search 补外网 | Dify workflow 引擎 |

---

## 13. 文档与契约变更清单

| 产物 | 变更 |
|------|------|
| `contracts/openapi.json` | 无新 Public API（搜索仅 Agent Tool）；可选未来 `POST /search` 给客户端调试 |
| `agent/prompts.py` | §并行、§搜索 |
| `evals/acceptance.py` | E11 从 DEFERRED → CORE（Phase S3 后） |
| `docs/CURRENT_IMPLEMENTATION.md` | 实现后更新 |
| ADR | 建议新增 `docs/adr/0002-search-and-parallel-read.md` 记录本决策 |

---

## 14. 评审问题（请确认）

1. **搜索供应商**：Tavily 为默认是否可接受？（国内网络与账单）
2. **CONFIRMED deadline**：是否强制 `source_id` **或** `evidence_urls`，还是允许用户 HITL 确认即可？
3. **并行上限**：单批 4、全 Run 搜索 6 是否合适？
4. **CONDITION_WATCH**：是否与 Phase S2 同期，还是明确后置？
5. **是否自动 archive search hit 为 Source**：默认关还是 CONFIRMED 时强制开？

---

## 附录 A：Tool 注册清单（实现后 30 Tools）

在现有 28 个基础上 **+2**：

- `search.web`
- `search.official`

仍 **不** 注册：`document.interpret`、`calendar.*`、`notification.push`（Push 走 Automation 通道）。

## 附录 B：示例 ToolResult（search.official）

```json
{
  "status": "SUCCESS",
  "code": "OK",
  "message": "Official-biased search completed.",
  "data": {
    "query": "2026 华为开发者大赛 报名截止",
    "retrieved_at": "2026-08-27T10:00:00+00:00",
    "provider": "tavily",
    "official_domains": ["developer.huawei.com"],
    "items": [
      {
        "title": "大赛报名须知",
        "url": "https://developer.huawei.com/...",
        "snippet": "报名截止时间为 2026年9月22日 ...",
        "domain": "developer.huawei.com",
        "published_at": null,
        "rank_score": 0.95
      }
    ]
  },
  "source_refs": ["https://developer.huawei.com/..."]
}
```
