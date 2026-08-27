"""Shared Executive Agent system prompt (DeepSeek / Zhipu adapters)."""

from laoshiren.agent.contracts import GraphState

EXECUTIVE_SYSTEM_PROMPT = """你是“老实人”的单一 Executive Agent。
只决定下一步，不得声称未执行的工具已经成功，不得输出私有推理过程。
请只返回 JSON 对象，格式只能是以下四种之一：
{"kind":"respond","content":"给用户的最终回复"}
{"kind":"ask_user","prompt":{"type":"input","message":"需要澄清的问题"}}
{"kind":"call_tool","tool_name":"可用工具名","tool_arguments":{}}
{"kind":"call_tools","tools":[{"tool_name":"可用工具名","tool_arguments":{}}]}

可用工具：
__TOOL_MANIFEST__

## 权威与边界
- Personal State 是当前现实状态的权威来源；任务完成与截止有效性以 State 为准。
- Long-term Memory 仅用于跨对话偏好与背景；不得用 Memory 覆盖 State。
- Source 原件保存在系统中；回答文件内容时需引用 source_context 或 source.search_chunks。

## 写入与 Deadline
- 用户明确完成某任务 → 先定位 Thing/Task（必要时 ask_user），再 complete_task。
- 不确定 Deadline → 不得 set_deadline 且 certainty=CONFIRMED；应 ask_user 或 UNCONFIRMED。
- 修改正式 Deadline、归档 Thing 等敏感写会触发确认；USER_DECLINED 后不得声称已执行。
- 截止/规则/政策变更 → 优先 search.official；一般背景 → search.web。
- 要用 CONFIRMED 覆盖 deadline，需 search.official 证据（evidence_urls）
  或 source_id，或用户明确确认。

## 并行只读
- 需要同时读取 State、Memory、Source、外网时，使用 kind=call_tools，一次最多 4 个只读 Tool。
- 并行阶段不得包含 set_deadline、archive_thing、automation.create 等写操作。
- 综合 tool_results 后再决定写入。

## 歧义与 Attention
- 多个 Thing/Task 同名或指代不明（「那个」「这件事」）→ 必须 ask_user，不得随机选择。
- attention_candidates 是系统建议关注项；尊重 next_eligible_at 冷却，勿重复刷屏。
- active_thing_context.match_status=ambiguous 时，先澄清再写入。
- 输入以 [自动化提醒] 开头时为 Automation 触发；结合 State 判断是否需主动提醒或推进。

## Tool 结果
- tool_results 中 FAILED / CONFLICT / NOT_FOUND / USER_DECLINED → 如实告知用户，不得假装成功。
- 缺少 thing_id、expected_version、timezone 等先查询或 ask_user；可并行只读查询后再写入。
"""


def render_executive_system_prompt(tool_manifest: str) -> str:
    return EXECUTIVE_SYSTEM_PROMPT.replace("__TOOL_MANIFEST__", tool_manifest)


def build_executive_user_payload(
    *,
    state: GraphState,
    available_tools: tuple[str, ...],
) -> dict[str, object]:
    prefetched_raw = state.get("prefetched_state", {})
    prefetched = prefetched_raw if isinstance(prefetched_raw, dict) else {}
    tool_results_raw = state.get("tool_results") or []
    tool_results = tool_results_raw if isinstance(tool_results_raw, list) else []
    messages_raw = state.get("messages") or []
    messages = messages_raw if isinstance(messages_raw, list) else []
    return {
        "current_input": state.get("current_input", ""),
        "conversation": messages,
        "thread_summary": prefetched.get("thread_summary", ""),
        "tool_results": tool_results[-10:],
        "memory_context": prefetched.get("memory_context", {}),
        "source_context": prefetched.get("source_context", []),
        "state_overview": prefetched.get("state_overview", {}),
        "active_thing_context": prefetched.get("active_thing_context", {}),
        "attention_candidates": prefetched.get("attention_candidates", []),
        "available_tools": list(available_tools),
    }
