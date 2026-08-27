# ADR 0002：Search Tool 与并行只读执行

- 状态：Proposed
- 日期：2026-08-27
- 详细设计：`docs/architecture/search-and-parallel-read-v1.md`

## 背景

PRD E11（并行查多元）与 E03/E06（外网/官方事实验证）在 V1 设计中有明确定义，但当前实现仅有顺序单 Tool 执行，且无 `search.*` 能力。Deadline Policy P02 已落地 `REQUIRE_MORE_CONTEXT`，缺少验证手段。

## 决策

1. **外网搜索**通过 `search.web` / `search.official` 两个 READ Tool 暴露，实现为 `SearchApplicationService` + `WebSearchPort`，默认 Tavily 适配器。
2. **`search.official` 与 `search.web` 共用同一 Port**，差异在 Application 层域名约束与排序，不维护两套搜索引擎集成。
3. **E11 并行**通过扩展 Executive 决策为 `call_tools`（只读批处理），在 Graph `execute` 节点内 `asyncio.gather` 实现；不引入固定多 Agent。
4. **并行阶段禁止写 Personal State**；mutation 仍在 fan-in 后由 Executive 单次 `call_tool` 执行。
5. **CONDITION_WATCH** 使用同一 `SearchApplicationService`，由 Automation Scheduler 调用，不经过 Executive Graph 轮询。
6. **Research Specialist Subgraph** 推迟到 V2，不在本 ADR 范围。

## 后果

### 正面

- 对齐 Tool/API Policy §12、Agent 架构 §24、§39 示例。
- 与 Clean Architecture、现有 ToolRegistry/Policy/ledger 一致。
- 可分 Phase S1–S3 交付，不阻塞当前核心闭环。

### 负面

- 增加第三方搜索 API 依赖与成本。
- Gateway 与 Prompt 需同时支持 `call_tool` / `call_tools`。
- Live eval 需额外 API Key。

## 备选方案（已否决）

| 方案 | 否决原因 |
|------|----------|
| 模型内置联网 | 不可审计，违反 ToolResult 契约 |
| 仅 Prompt 要求「请用户自己查」 | 无法满足 E06/官方验证产品行为 |
| LangGraph Send 作为 V1 默认 | 复杂度过高，E11 不需动态 N |
| 客户端内置搜索 | 违反「客户端不复制 Agent 决策」 |
