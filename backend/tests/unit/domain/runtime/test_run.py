from uuid import uuid4

import pytest

from laoshiren.domain.runtime.entities import AgentRun, RunStatus, RunTrigger


def make_run() -> AgentRun:
    return AgentRun(
        user_id=uuid4(),
        thread_id=uuid4(),
        trigger=RunTrigger.USER_MESSAGE,
        idempotency_key="runtime-unit-key",
    )


def test_run_wait_resume_and_complete_state_machine() -> None:
    run = make_run()
    run.start(phase="understanding", label="正在理解需求")
    assert run.status is RunStatus.RUNNING
    assert run.version == 2

    interrupt_id = uuid4()
    run.wait_for_user(
        interrupt_id=interrupt_id,
        payload={"type": "CLARIFICATION", "question": "请选择事务"},
    )
    assert run.status is RunStatus.WAITING_USER

    run.resume(interrupt_id=interrupt_id, response={"thing_id": str(uuid4())})
    assert run.status is RunStatus.QUEUED
    assert run.resume_payload is not None

    run.start(phase="resuming", label="正在继续处理")
    final_message_id = uuid4()
    run.complete(final_message_id=final_message_id)
    assert run.status is RunStatus.COMPLETED
    assert run.final_message_id == final_message_id
    assert run.completed_at is not None


def test_run_rejects_invalid_resume_and_terminal_cancel() -> None:
    run = make_run()
    with pytest.raises(ValueError, match="waiting for user"):
        run.resume(interrupt_id=uuid4(), response={})

    run.start()
    run.complete(final_message_id=uuid4())
    with pytest.raises(ValueError, match="terminal"):
        run.cancel()
