import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
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
    InteractionResponseRequest,
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


@runs_router.post(
    "/{run_id}/interactions/{interaction_id}/respond",
    response_model=RunResponse,
)
async def respond_to_interaction(
    run_id: UUID,
    interaction_id: UUID,
    payload: InteractionResponseRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> RunResponse:
    value = await container.runtime.resume_run(
        user_id=user_id,
        run_id=run_id,
        interrupt_id=interaction_id,
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
        "sequence": event.sequence,
        "event": event_name,
        "run_id": str(event.run_id),
        "occurred_at": event.occurred_at.isoformat(),
        "visibility": event.visibility,
        "schema_version": event.schema_version,
        "data": event.data,
    }
    data = json.dumps(envelope, default=str)
    return f"id: {event.sequence}\nevent: {event_name}\ndata: {data}\n\n"


@runs_router.get("/{run_id}/events", response_class=StreamingResponse)
async def stream_run_events(
    run_id: UUID,
    request: Request,
    container: ContainerDependency,
    user_id: CurrentUserId,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    follow: bool = True,
) -> StreamingResponse:
    after_sequence: int | None = None
    legacy_event_id: UUID | None = None
    if last_event_id is not None:
        try:
            after_sequence = int(last_event_id)
            if after_sequence < 0:
                raise ValueError
        except ValueError:
            try:
                legacy_event_id = UUID(last_event_id)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Last-Event-ID must be a non-negative sequence or UUID.",
                ) from exc
    # Subscribe before reading the durable catch-up window.  Redis is only a
    # best-effort live hint, but this ordering prevents a frame published in
    # the replay/subscribe gap from being needlessly lost.
    subscription = (
        await container.runtime.subscribe_to_live_frames(run_id=run_id) if follow else None
    )
    try:
        initial = await container.runtime.list_events(
            user_id=user_id,
            run_id=run_id,
            after_event_id=legacy_event_id,
            after_sequence=after_sequence,
        )
    except BaseException:
        if subscription is not None:
            await subscription.close()
        raise

    async def generate() -> AsyncIterator[str]:
        # A legacy UUID cursor is only used for the first DB query. Advance to
        # the returned durable sequence before entering the live loop, or a
        # reconnect could replay the complete stream indefinitely.
        try:
            cursor = initial[-1].sequence if initial else after_sequence
            pending = initial
            while True:
                for event in pending:
                    cursor = event.sequence
                    yield _encode_event(event)
                run = await container.runtime.get_run(user_id=user_id, run_id=run_id)
                if not follow or run.status in TERMINAL_RUN_STATUSES:
                    break
                if await request.is_disconnected():
                    break
                signal = (
                    await subscription.wait(timeout_seconds=0.5)
                    if subscription is not None
                    else await container.runtime.wait_for_wakeup(run_id=run_id, timeout_seconds=0.5)
                )
                if signal is not None:
                    frame = {
                        "run_id": str(signal.run_id),
                        "frame_type": signal.frame_type,
                        "emitted_at": signal.emitted_at.isoformat(),
                        "data": signal.data,
                    }
                    yield (
                        f"event: {signal.frame_type}\ndata: {json.dumps(frame, default=str)}\n\n"
                    )
                else:
                    yield ": heartbeat\n\n"
                pending = await container.runtime.list_events(
                    user_id=user_id, run_id=run_id, after_sequence=cursor
                )
        finally:
            if subscription is not None:
                await subscription.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
