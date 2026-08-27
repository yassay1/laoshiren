"""PRD §23 acceptance scenarios mapped for evals and deterministic tests."""

from dataclasses import dataclass
from enum import StrEnum


class ScenarioPhase(StrEnum):
    CORE = "core"
    LIVE = "live"
    DEFERRED = "deferred"


@dataclass(frozen=True, slots=True)
class AcceptanceScenario:
    code: str
    title: str
    prompt: str
    expectation: str
    phase: ScenarioPhase = ScenarioPhase.CORE


ACCEPTANCE_SCENARIOS: tuple[AcceptanceScenario, ...] = (
    AcceptanceScenario(
        "E01",
        "状态更新",
        "Demo做完了。",
        "对应 Task 变为 DONE，其他 Task 不受影响",
    ),
    AcceptanceScenario(
        "E02",
        "状态查询",
        "这个项目现在还剩什么？",
        "根据 Personal State 返回 pending tasks",
    ),
    AcceptanceScenario(
        "E03",
        "不确定 Deadline",
        "听说截止日期改到22号了。",
        "不得未经验证直接 CONFIRMED deadline",
    ),
    AcceptanceScenario(
        "E04",
        "跨 Thread 记忆",
        "之前我们定的回复风格是什么？",
        "可从 Long-term Memory 召回",
    ),
    AcceptanceScenario(
        "E05",
        "文件关联",
        "请把这份资料关联到当前项目。",
        "Source 可关联 Thing 且保留引用",
    ),
    AcceptanceScenario(
        "E06",
        "文件产生状态变化",
        "根据附件里的正式 deadline 更新。",
        "识别变化并按 Policy 判断是否更新",
    ),
    AcceptanceScenario(
        "E07",
        "Attention",
        "聊聊别的。",
        "在合适时机可提及高优先级关注项",
        phase=ScenarioPhase.LIVE,
    ),
    AcceptanceScenario(
        "E08",
        "Attention 冷却",
        "继续。",
        "刚提醒过的事项不重复刷屏",
        phase=ScenarioPhase.LIVE,
    ),
    AcceptanceScenario(
        "E09",
        "Automation",
        "明天下午3点提醒我提交材料。",
        "创建 ONE_SHOT automation",
    ),
    AcceptanceScenario(
        "E10",
        "Push",
        "（离线触发）",
        "Automation 到期收到 Push",
        phase=ScenarioPhase.DEFERRED,
    ),
    AcceptanceScenario(
        "E11",
        "并行执行",
        "同时查官网、文件和当前进度。",
        "并行独立任务并融合",
        phase=ScenarioPhase.DEFERRED,
    ),
    AcceptanceScenario(
        "E12",
        "Tool 失败诚实",
        "完成一个不存在的任务 00000000-0000-0000-0000-000000000099。",
        "Tool 失败时不得声称成功",
    ),
    AcceptanceScenario(
        "E13",
        "多 Thing 歧义",
        "帮我把 Demo 标记完成。",
        "上下文不足时必须 ask_user",
    ),
    AcceptanceScenario(
        "E14",
        "Memory/State 边界",
        "那个任务完成了吗？",
        "任务状态来自 State 而非 Memory",
    ),
    AcceptanceScenario(
        "E15",
        "Source 保留",
        "我上传的文件还在吗？",
        "保留 Source 引用而非仅摘要",
    ),
)

CORE_SCENARIO_CODES = frozenset(
    scenario.code for scenario in ACCEPTANCE_SCENARIOS if scenario.phase is ScenarioPhase.CORE
)


def get_acceptance_scenario(code: str) -> AcceptanceScenario:
    for scenario in ACCEPTANCE_SCENARIOS:
        if scenario.code == code:
            return scenario
    raise KeyError(f"Unknown acceptance scenario: {code}")
