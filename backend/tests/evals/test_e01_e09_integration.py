import os
from uuid import UUID, uuid4

import pytest

from evals.acceptance import CORE_SCENARIO_CODES, get_acceptance_scenario
from laoshiren.agent.contracts import DecisionKind, ExecutiveDecision, GraphState
from laoshiren.bootstrap import build_agent_worker
from laoshiren.domain.personal_state.value_objects import TaskStatus
from laoshiren.domain.runtime.entities import RunStatus
from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


class E01CompleteTaskGateway:
    def __init__(self, *, task_id: str, thing_version: int) -> None:
        self._task_id = task_id
        self._thing_version = thing_version
        self._completed = False

    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
    ) -> ExecutiveDecision:
        if self._completed or state.get("tool_results"):
            return ExecutiveDecision(DecisionKind.RESPOND, content="Demo 已标记完成。")
        return ExecutiveDecision(
            DecisionKind.CALL_TOOL,
            tool_name="state.complete_task",
            tool_arguments={
                "task_id": self._task_id,
                "expected_version": 1,
            },
        )


@pytest.mark.parametrize("code", sorted(CORE_SCENARIO_CODES - {"E04", "E05", "E06", "E07", "E08"}))
async def test_core_scenario_worker_smoke(code: str) -> None:
    """Each core scenario can create a durable Run and reach a terminal/working state."""
    scenario = get_acceptance_scenario(code)
    app = create_app()
    runtime = app.state.container.runtime
    user_id = UUID(app.state.container.settings.dev_user_id)
    await app.state.container.checkpoints.start()
    try:
        thread = await runtime.create_thread(
            user_id=user_id,
            title=f"eval:{code}",
            idempotency_key=f"eval-thread-{code}-{uuid4()}",
        )
        gateway: object
        if code == "E01":
            thing = await app.state.container.personal_state.create_thing(
                user_id=user_id,
                name="秋季 Demo",
                action_id="eval.setup",
                idempotency_key=f"eval-thing-{uuid4()}",
                reason="Eval setup",
            )
            task = await app.state.container.personal_state.create_task(
                user_id=user_id,
                thing_id=thing.id,
                title="Demo",
                action_id="eval.setup",
                idempotency_key=f"eval-task-{uuid4()}",
                reason="Eval setup",
            )
            gateway = E01CompleteTaskGateway(task_id=str(task.id), thing_version=thing.version)
        else:
            gateway = _RespondGateway(scenario.prompt)

        worker = build_agent_worker(app.state.container, gateway)  # type: ignore[arg-type]
        run = await runtime.create_user_run(
            user_id=user_id,
            thread_id=thread.id,
            content=scenario.prompt,
            source_ids=[],
            idempotency_key=f"eval-run-{code}-{uuid4()}",
        )
        status = await worker.run_once(user_id=user_id, run_id=run.id)
        assert status in {RunStatus.COMPLETED, RunStatus.WAITING_USER}
        if code == "E01":
            tasks = await app.state.container.personal_state.get_tasks(
                user_id=user_id, thing_id=thing.id
            )
            demo = next(item for item in tasks if item.title == "Demo")
            assert demo.status is TaskStatus.DONE
    finally:
        await app.state.container.checkpoints.stop()
        await app.state.container.database.dispose()


class _RespondGateway:
    def __init__(self, echo: str) -> None:
        self._echo = echo

    async def decide(
        self, *, state: GraphState, available_tools: tuple[str, ...], tool_manifest: str
    ) -> ExecutiveDecision:
        return ExecutiveDecision(DecisionKind.RESPOND, content=f"收到：{self._echo}")
