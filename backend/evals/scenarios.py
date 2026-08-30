from dataclasses import dataclass

from evals.acceptance import ACCEPTANCE_SCENARIOS


@dataclass(frozen=True, slots=True)
class LiveScenario:
    key: str
    prompt: str
    expected: str


def _live_from_acceptance(code: str) -> LiveScenario:
    scenario = next(item for item in ACCEPTANCE_SCENARIOS if item.code == code)
    return LiveScenario(
        key=code.lower(),
        prompt=scenario.prompt,
        expected=scenario.expectation,
    )


SCENARIOS = (
    LiveScenario("direct_answer", "用一句话说明你能帮我做什么。", "non-empty direct answer"),
    _live_from_acceptance("E01"),
    _live_from_acceptance("E03"),
    _live_from_acceptance("E09"),
    _live_from_acceptance("E12"),
    _live_from_acceptance("E13"),
    LiveScenario("create_thing", "创建一个 Thing：准备秋季旅行。", "create Thing tool"),
    LiveScenario("create_task", "创建任务：周五前订火车票。", "create task tool"),
    LiveScenario("complete_task", "把刚创建的订火车票任务标记为完成。", "complete task tool"),
    LiveScenario("multi_tool", "创建‘搬家’事项，并在里面创建‘联系搬家公司’任务。", "two tools"),
    LiveScenario("clarification", "帮我把那个重要的事情办了。", "clarification interrupt"),
    LiveScenario("hitl", "删除我刚才创建的搬家事项。", "confirmation interrupt"),
    LiveScenario(
        "tool_failure",
        "完成一个不存在的任务，ID 是 00000000-0000-0000-0000-000000000099。",
        "no false success",
    ),
    LiveScenario("memory_write", "请记住：我出差时更喜欢住安静的酒店。", "memory candidate"),
    LiveScenario("profile_update", "记住我以后希望你用简短中文回答。", "PROFILE update"),
    LiveScenario("memory_recall", "我出差时偏好什么样的酒店？", "cross-thread recall"),
    LiveScenario(
        "source_evidence",
        "只根据我附加的来源回答并标明证据；如果没有来源就明确说没有。",
        "no invented evidence",
    ),
    LiveScenario("automation", "每天早上 8 点提醒我查看今天最重要的任务。", "automation tool"),
    LiveScenario("long_thread", "总结目前对话，并保留最近的明确要求。", "bounded context"),
    LiveScenario("ambiguous_language", "那个事儿下周差不多弄一下。", "ask rather than invent"),
)


def select_scenarios(value: str) -> tuple[LiveScenario, ...]:
    requested = {item.strip() for item in value.split(",") if item.strip()}
    if not requested or requested == {"default"}:
        requested = {"direct_answer"}
    if requested == {"all"}:
        return SCENARIOS
    known = {scenario.key for scenario in SCENARIOS}
    unknown = requested - known
    if unknown:
        raise ValueError(f"Unknown live eval scenarios: {', '.join(sorted(unknown))}")
    return tuple(scenario for scenario in SCENARIOS if scenario.key in requested)
