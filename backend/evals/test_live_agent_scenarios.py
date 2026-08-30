import json
import os
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

import pytest

from evals.scenarios import LiveScenario, select_scenarios
from laoshiren.bootstrap import build_configured_agent_worker
from laoshiren.domain.runtime.entities import RunStatus
from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.live_model,
    pytest.mark.gate_a,
    pytest.mark.skipif(
        os.getenv("RUN_MODEL_EVALS") != "1",
        reason="Set RUN_MODEL_EVALS=1 to spend model quota on live evals.",
    ),
]


@pytest.mark.parametrize(
    "scenario",
    select_scenarios(os.getenv("MODEL_EVAL_SCENARIOS", "default")),
    ids=lambda scenario: scenario.key,
)
async def test_live_agent_scenario(scenario: LiveScenario) -> None:
    # Kept outside normal testpaths: this is a deliberately paid, opt-in trajectory smoke.
    key = scenario.key
    prompt = scenario.prompt
    expected = scenario.expected
    app = create_app()
    container = app.state.container
    if not container.settings.model_api_key:
        pytest.skip("MODEL_API_KEY is not configured.")
    user_id = UUID(container.settings.dev_user_id)
    started = monotonic()
    await container.checkpoints.start()
    try:
        thread = await container.runtime.create_thread(
            user_id=user_id,
            title=f"live-eval:{key}",
            idempotency_key=f"live-eval-thread:{uuid4()}",
        )
        run = await container.runtime.create_user_run(
            user_id=user_id,
            thread_id=thread.id,
            content=prompt,
            source_ids=[],
            idempotency_key=f"live-eval-run:{uuid4()}",
        )
        status = await build_configured_agent_worker(container).run_once(
            user_id=user_id, run_id=run.id
        )
        messages = await container.runtime.list_messages(user_id=user_id, thread_id=thread.id)
        events = await container.runtime.list_events(user_id=user_id, run_id=run.id)
        record = {
            "scenario": key,
            "expected": expected,
            "run_id": str(run.id),
            "status": status.value,
            "latency_seconds": round(monotonic() - started, 3),
            "final_answer": messages[-1].content if messages else None,
            "trajectory": [
                {"sequence": event.sequence, "type": event.event.value, "data": event.data}
                for event in events
            ],
            "token_usage": None,
        }
        output = Path(os.getenv("MODEL_EVAL_OUTPUT", "var/evals/live-agent.jsonl"))
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        assert status in {RunStatus.COMPLETED, RunStatus.WAITING_USER}
        assert events
        if status is RunStatus.COMPLETED:
            assert messages[-1].content.strip()
    finally:
        await container.checkpoints.stop()
        await container.database.dispose()
