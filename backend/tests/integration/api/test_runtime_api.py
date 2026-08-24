import os
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from laoshiren.domain.runtime.entities import RunEventType
from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def test_thread_run_interrupt_resume_completion_and_event_replay() -> None:
    app = create_app()
    headers = {"Authorization": "Bearer change-me"}
    thread_ids: list[UUID] = []
    run_ids: list[UUID] = []
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=headers
        ) as client:
            thread_key = f"runtime-thread-{uuid4()}"
            created_thread = await client.post(
                "/api/v1/threads",
                headers={"Idempotency-Key": thread_key},
                json={"title": "运行时测试对话"},
            )
            replayed_thread = await client.post(
                "/api/v1/threads",
                headers={"Idempotency-Key": thread_key},
                json={"title": "运行时测试对话"},
            )
            assert created_thread.status_code == 201
            assert replayed_thread.json()["replayed"] is True
            thread_id = UUID(created_thread.json()["id"])
            thread_ids.append(thread_id)

            run_key = f"runtime-run-{uuid4()}"
            created_run = await client.post(
                "/api/v1/runs",
                headers={"Idempotency-Key": run_key},
                json={
                    "thread_id": str(thread_id),
                    "message": {"type": "text", "content": "请继续处理演示任务"},
                    "source_ids": [],
                },
            )
            replayed_run = await client.post(
                "/api/v1/runs",
                headers={"Idempotency-Key": run_key},
                json={
                    "thread_id": str(thread_id),
                    "message": {"type": "text", "content": "请继续处理演示任务"},
                    "source_ids": [],
                },
            )
            assert created_run.status_code == 202
            assert created_run.json()["status"] == "QUEUED"
            assert replayed_run.json()["replayed"] is True
            run_id = UUID(created_run.json()["id"])
            run_ids.append(run_id)

            messages = await client.get(f"/api/v1/threads/{thread_id}/messages")
            assert len(messages.json()) == 1
            assert messages.json()[0]["role"] == "USER"

            started = await app.state.container.runtime.start_run(
                user_id=UUID(app.state.container.settings.dev_user_id),
                run_id=run_id,
                phase="understanding",
                label="正在理解需求",
            )
            waiting = await app.state.container.runtime.require_input(
                user_id=UUID(app.state.container.settings.dev_user_id),
                run_id=run_id,
                payload={
                    "type": "CLARIFICATION",
                    "question": "你指的是哪一个演示任务？",
                    "options": ["比赛演示", "论文演示"],
                },
            )
            assert started.status.value == "RUNNING"
            assert waiting.status.value == "WAITING_USER"
            assert waiting.interrupt_id is not None

            waiting_events = await app.state.container.runtime.list_events(
                user_id=UUID(app.state.container.settings.dev_user_id), run_id=run_id
            )
            interrupt_event = next(
                event
                for event in waiting_events
                if event.event is RunEventType.INTERRUPT_REQUIRED
            )
            waiting_replay = await client.get(
                f"/api/v1/runs/{run_id}/events?follow=false",
                headers={"Last-Event-ID": str(interrupt_event.id)},
            )
            assert "interrupt.required" not in waiting_replay.text

            invalid_resume = await client.post(
                f"/api/v1/runs/{run_id}/resume",
                headers={"Idempotency-Key": f"runtime-resume-{uuid4()}"},
                json={
                    "interrupt_id": str(uuid4()),
                    "response": {"selection": "比赛演示"},
                    "expected_version": waiting.version,
                },
            )
            assert invalid_resume.status_code == 409

            resume_key = f"runtime-resume-{uuid4()}"
            resumed = await client.post(
                f"/api/v1/runs/{run_id}/resume",
                headers={"Idempotency-Key": resume_key},
                json={
                    "interrupt_id": str(waiting.interrupt_id),
                    "response": {"selection": "比赛演示"},
                    "expected_version": waiting.version,
                },
            )
            replayed_resume = await client.post(
                f"/api/v1/runs/{run_id}/resume",
                headers={"Idempotency-Key": resume_key},
                json={
                    "interrupt_id": str(waiting.interrupt_id),
                    "response": {"selection": "比赛演示"},
                    "expected_version": waiting.version,
                },
            )
            assert resumed.json()["status"] == "QUEUED"
            assert replayed_resume.json()["replayed"] is True

            await app.state.container.runtime.start_run(
                user_id=UUID(app.state.container.settings.dev_user_id),
                run_id=run_id,
                phase="responding",
                label="正在整理结果",
            )
            delta = await app.state.container.runtime.emit_event(
                user_id=UUID(app.state.container.settings.dev_user_id),
                run_id=run_id,
                event_type=RunEventType.ASSISTANT_DELTA,
                data={"message_id": str(uuid4()), "delta": "已经确认"},
            )
            completed = await app.state.container.runtime.complete_run(
                user_id=UUID(app.state.container.settings.dev_user_id),
                run_id=run_id,
                content="已经确认比赛演示任务。",
            )
            assert completed.status.value == "COMPLETED"

            completed_events = await app.state.container.runtime.list_events(
                user_id=UUID(app.state.container.settings.dev_user_id), run_id=run_id
            )
            sequences = [event.sequence for event in completed_events]
            assert sequences == sorted(sequences)
            assert len(sequences) == len(set(sequences))

            replay_stream = await client.get(
                f"/api/v1/runs/{run_id}/events?follow=false",
                headers={"Last-Event-ID": str(delta.id)},
            )
            assert replay_stream.status_code == 200
            assert replay_stream.headers["content-type"].startswith("text/event-stream")
            assert "run.completed" in replay_stream.text
            assert "assistant.delta" not in replay_stream.text

            final_messages = await client.get(f"/api/v1/threads/{thread_id}/messages")
            assert [item["role"] for item in final_messages.json()] == ["USER", "ASSISTANT"]
            current = await client.get(f"/api/v1/runs/{run_id}")
            assert current.json()["final_message_id"] == final_messages.json()[-1]["id"]

            second_run = await client.post(
                "/api/v1/runs",
                headers={"Idempotency-Key": f"runtime-run-{uuid4()}"},
                json={
                    "thread_id": str(thread_id),
                    "message": {"type": "text", "content": "取消这次运行"},
                },
            )
            second_run_id = UUID(second_run.json()["id"])
            run_ids.append(second_run_id)
            cancelled = await client.post(
                f"/api/v1/runs/{second_run_id}/cancel",
                headers={"Idempotency-Key": f"runtime-cancel-{uuid4()}"},
                json={"expected_version": 1},
            )
            assert cancelled.json()["status"] == "CANCELLED"

            archived = await client.delete(f"/api/v1/threads/{thread_id}")
            active_threads = await client.get("/api/v1/threads")
            all_threads = await client.get("/api/v1/threads?include_archived=true")
            assert archived.json()["archived_at"] is not None
            assert all(item["id"] != str(thread_id) for item in active_threads.json())
            assert any(item["id"] == str(thread_id) for item in all_threads.json())
    finally:
        async with app.state.container.database.engine.begin() as connection:
            for statement in (
                "DELETE FROM run_operations WHERE run_id = ANY(:run_ids)",
                "DELETE FROM run_events WHERE run_id = ANY(:run_ids)",
                "DELETE FROM messages WHERE thread_id = ANY(:thread_ids)",
                "DELETE FROM agent_runs WHERE id = ANY(:run_ids)",
                "DELETE FROM threads WHERE id = ANY(:thread_ids)",
            ):
                await connection.execute(
                    text(statement), {"run_ids": run_ids, "thread_ids": thread_ids}
                )
        await app.state.container.database.dispose()
