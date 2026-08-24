import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status
from fastapi.responses import StreamingResponse

from laoshiren.application.runtime.dto import RunEventDTO
from laoshiren.domain.runtime.entities import TERMINAL_RUN_STATUSES
from laoshiren.presentation.api.dependencies import (
    ContainerDependency,
    CurrentUserId,
    IdempotencyKey,
)
from laoshiren.presentation.api.schemas.runtime import (
    CancelRunRequest,
    CreateRunRequest,
    CreateThreadRequest,
    MessageResponse,
    ResumeRunRequest,
    RunResponse,
    ThreadResponse,
)

threads_router = APIRouter(prefix="/threads", tags=["threads"])
runs_router = APIRouter(prefix="/runs", tags=["runs"])


@threads_router.post("", response_model=ThreadResponse, status_code=status.HTTP_201_CREATED)
async def create_thread(
    payload: CreateThreadRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> ThreadResponse:
    value = await container.runtime.create_thread(
        user_id=user_id,
        title=payload.title,
        active_thing_id=payload.active_thing_id,
        idempotency_key=idempotency_key,
    )
    return ThreadResponse.from_dto(value)


@threads_router.get("", response_model=list[ThreadResponse])
async def list_threads(
    container: ContainerDependency,
    user_id: CurrentUserId,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    include_archived: bool = False,
) -> list[ThreadResponse]:
    values = await container.runtime.list_threads(
        user_id=user_id, limit=limit, include_archived=include_archived
    )
    return [ThreadResponse.from_dto(value) for value in values]


@threads_router.get("/{thread_id}", response_model=ThreadResponse)
async def get_thread(
    thread_id: UUID, container: ContainerDependency, user_id: CurrentUserId
) -> ThreadResponse:
    value = await container.runtime.get_thread(user_id=user_id, thread_id=thread_id)
    return ThreadResponse.from_dto(value)


@threads_router.delete("/{thread_id}", response_model=ThreadResponse)
async def archive_thread(
    thread_id: UUID, container: ContainerDependency, user_id: CurrentUserId
) -> ThreadResponse:
    value = await container.runtime.archive_thread(user_id=user_id, thread_id=thread_id)
    return ThreadResponse.from_dto(value)


@threads_router.get("/{thread_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    thread_id: UUID,
    container: ContainerDependency,
    user_id: CurrentUserId,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[MessageResponse]:
    values = await container.runtime.list_messages(
        user_id=user_id, thread_id=thread_id, limit=limit
    )
    return [MessageResponse.from_dto(value) for value in values]


@runs_router.post("", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    payload: CreateRunRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> RunResponse:
    value = await container.runtime.create_user_run(
        user_id=user_id,
        thread_id=payload.thread_id,
        content=payload.message.content,
        source_ids=payload.source_ids,
        idempotency_key=idempotency_key,
    )
    return RunResponse.from_dto(value)


@runs_router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: UUID, container: ContainerDependency, user_id: CurrentUserId
) -> RunResponse:
    value = await container.runtime.get_run(user_id=user_id, run_id=run_id)
    return RunResponse.from_dto(value)


@runs_router.post("/{run_id}/resume", response_model=RunResponse)
async def resume_run(
    run_id: UUID,
    payload: ResumeRunRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> RunResponse:
    value = await container.runtime.resume_run(
        user_id=user_id,
        run_id=run_id,
        interrupt_id=payload.interrupt_id,
        response=payload.response,
        expected_version=payload.expected_version,
        idempotency_key=idempotency_key,
    )
    return RunResponse.from_dto(value)


@runs_router.post("/{run_id}/cancel", response_model=RunResponse)
async def cancel_run(
    run_id: UUID,
    payload: CancelRunRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> RunResponse:
    value = await container.runtime.cancel_run(
        user_id=user_id,
        run_id=run_id,
        expected_version=payload.expected_version,
        idempotency_key=idempotency_key,
    )
    return RunResponse.from_dto(value)


def _encode_event(event: RunEventDTO) -> str:
    event_id = event.id
    event_name = event.event
    envelope = {
        "event_id": str(event_id),
        "event": event_name,
        "run_id": str(event.run_id),
        "occurred_at": event.occurred_at.isoformat(),
        "data": event.data,
    }
    return f"id: {event_id}\nevent: {event_name}\ndata: {json.dumps(envelope, default=str)}\n\n"


@runs_router.get("/{run_id}/events", response_class=StreamingResponse)
async def stream_run_events(
    run_id: UUID,
    request: Request,
    container: ContainerDependency,
    user_id: CurrentUserId,
    last_event_id: Annotated[UUID | None, Header(alias="Last-Event-ID")] = None,
    follow: bool = True,
) -> StreamingResponse:
    initial = await container.runtime.list_events(
        user_id=user_id, run_id=run_id, after_event_id=last_event_id
    )

    async def generate() -> AsyncIterator[str]:
        cursor = last_event_id
        pending = initial
        while True:
            for event in pending:
                cursor = event.id
                yield _encode_event(event)
            run = await container.runtime.get_run(user_id=user_id, run_id=run_id)
            if not follow or run.status in TERMINAL_RUN_STATUSES:
                break
            if await request.is_disconnected():
                break
            await asyncio.sleep(0.5)
            pending = await container.runtime.list_events(
                user_id=user_id, run_id=run_id, after_event_id=cursor
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
