from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from laoshiren.domain.personal_state.value_objects import ThingStatus
from laoshiren.presentation.api.dependencies import (
    ContainerDependency,
    CurrentUserId,
    IdempotencyKey,
)
from laoshiren.presentation.api.schemas.personal_state import (
    BlockerResponse,
    CreateBlockerRequest,
    CreateTaskRequest,
    CreateThingRelationRequest,
    CreateThingRequest,
    MutationResponse,
    SetDeadlineRequest,
    StateMutationResponse,
    TaskResponse,
    ThingDateResponse,
    ThingRelationCreatedResponse,
    ThingRelationResponse,
    ThingResponse,
    TimelineEventResponse,
    UpdateThingRequest,
)
from laoshiren.presentation.api.schemas.sources import (
    LinkSourceRequest,
    LinkSourceResponse,
    SourceResponse,
)

router = APIRouter(prefix="/things", tags=["things"])


@router.get("", response_model=list[ThingResponse])
async def list_things(
    container: ContainerDependency,
    user_id: CurrentUserId,
    status_filter: Annotated[ThingStatus | None, Query(alias="status")] = None,
    q: str | None = None,
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ThingResponse]:
    things = await container.personal_state.get_things(
        user_id=user_id,
        status=status_filter,
        query=q,
        cursor=cursor,
        limit=limit,
    )
    return [ThingResponse.from_dto(thing) for thing in things]


@router.post("", response_model=ThingResponse, status_code=status.HTTP_201_CREATED)
async def create_thing(
    request: CreateThingRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> ThingResponse:
    thing = await container.personal_state.create_thing(
        user_id=user_id,
        name=request.name,
        action_id="api.create_thing",
        idempotency_key=idempotency_key,
        reason="User created Thing through Product API.",
    )
    return ThingResponse.from_dto(thing)


@router.get("/{thing_id}", response_model=ThingResponse)
async def get_thing(
    thing_id: UUID,
    container: ContainerDependency,
    user_id: CurrentUserId,
) -> ThingResponse:
    thing = await container.personal_state.get_thing(user_id=user_id, thing_id=thing_id)
    return ThingResponse.from_dto(thing)


@router.patch("/{thing_id}", response_model=ThingResponse)
async def update_thing(
    thing_id: UUID,
    request: UpdateThingRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> ThingResponse:
    thing = await container.personal_state.update_thing(
        user_id=user_id,
        thing_id=thing_id,
        expected_version=request.expected_version,
        name=request.name,
        status=request.status,
        current_stage=request.current_stage,
        update_current_stage="current_stage" in request.model_fields_set,
        action_id="api.update_thing",
        idempotency_key=idempotency_key,
        reason=request.reason,
    )
    return ThingResponse.from_dto(thing)


@router.post("/{thing_id}/dates", response_model=MutationResponse)
@router.post("/{thing_id}/deadline", response_model=MutationResponse, include_in_schema=False)
async def set_deadline(
    thing_id: UUID,
    request: SetDeadlineRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> MutationResponse:
    result = await container.personal_state.set_deadline(
        user_id=user_id,
        thing_id=thing_id,
        kind=request.kind,
        value=request.value,
        timezone_name=request.timezone,
        precision=request.precision,
        certainty=request.certainty,
        is_primary=request.is_primary,
        expected_version=request.expected_version,
        action_id="api.set_deadline",
        idempotency_key=idempotency_key,
        reason=request.reason,
    )
    return MutationResponse(
        mutation_id=result.mutation_id,
        target_id=result.target_id,
        target_version=result.target_version,
        replayed=result.replayed,
    )


@router.get("/{thing_id}/dates", response_model=list[ThingDateResponse])
async def list_dates(
    thing_id: UUID,
    container: ContainerDependency,
    user_id: CurrentUserId,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[ThingDateResponse]:
    dates = await container.personal_state.get_dates(
        user_id=user_id, thing_id=thing_id, limit=limit
    )
    return [ThingDateResponse.from_dto(thing_date) for thing_date in dates]


@router.get("/{thing_id}/timeline", response_model=list[TimelineEventResponse])
async def list_timeline(
    thing_id: UUID,
    container: ContainerDependency,
    user_id: CurrentUserId,
    event_type: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[TimelineEventResponse]:
    events = await container.personal_state.get_timeline(
        user_id=user_id,
        thing_id=thing_id,
        event_type=event_type,
        limit=limit,
    )
    return [TimelineEventResponse.from_dto(event) for event in events]


@router.get("/{thing_id}/history", response_model=list[StateMutationResponse])
async def list_state_history(
    thing_id: UUID,
    container: ContainerDependency,
    user_id: CurrentUserId,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[StateMutationResponse]:
    mutations = await container.personal_state.get_state_history(
        user_id=user_id, thing_id=thing_id, limit=limit
    )
    return [StateMutationResponse.from_dto(mutation) for mutation in mutations]


@router.get("/{thing_id}/blockers", response_model=list[BlockerResponse])
async def list_blockers(
    thing_id: UUID,
    container: ContainerDependency,
    user_id: CurrentUserId,
) -> list[BlockerResponse]:
    blockers = await container.personal_state.get_blockers(
        user_id=user_id, thing_id=thing_id
    )
    return [BlockerResponse.from_dto(blocker) for blocker in blockers]


@router.post(
    "/{thing_id}/blockers",
    response_model=BlockerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_blocker(
    thing_id: UUID,
    request: CreateBlockerRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> BlockerResponse:
    blocker = await container.personal_state.create_blocker(
        user_id=user_id,
        thing_id=thing_id,
        description=request.description,
        severity=request.severity,
        task_id=request.task_id,
        source_id=request.source_id,
        action_id="api.create_blocker",
        idempotency_key=idempotency_key,
        reason=request.reason,
    )
    return BlockerResponse.from_dto(blocker)


@router.get("/{thing_id}/relations", response_model=list[ThingRelationResponse])
async def list_relations(
    thing_id: UUID,
    container: ContainerDependency,
    user_id: CurrentUserId,
) -> list[ThingRelationResponse]:
    relations = await container.personal_state.get_relations(
        user_id=user_id, thing_id=thing_id
    )
    return [ThingRelationResponse.from_dto(relation) for relation in relations]


@router.post("/{thing_id}/relations", response_model=ThingRelationCreatedResponse)
async def create_relation(
    thing_id: UUID,
    request: CreateThingRelationRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> ThingRelationCreatedResponse:
    created = await container.personal_state.add_relation(
        user_id=user_id,
        from_thing_id=thing_id,
        to_thing_id=request.to_thing_id,
        relation_type=request.relation_type,
        note=request.note,
        action_id="api.add_thing_relation",
        idempotency_key=idempotency_key,
        reason=request.reason,
    )
    return ThingRelationCreatedResponse(created=created)


@router.get("/{thing_id}/sources", response_model=list[SourceResponse])
async def list_sources(
    thing_id: UUID,
    container: ContainerDependency,
    user_id: CurrentUserId,
) -> list[SourceResponse]:
    sources = await container.sources.list_for_thing(user_id=user_id, thing_id=thing_id)
    return [SourceResponse.from_dto(source) for source in sources]


@router.post("/{thing_id}/sources/{source_id}", response_model=LinkSourceResponse)
async def link_source(
    thing_id: UUID,
    source_id: UUID,
    request: LinkSourceRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> LinkSourceResponse:
    created = await container.sources.link_to_thing(
        user_id=user_id,
        thing_id=thing_id,
        source_id=source_id,
        relation_type=request.relation_type,
        relevance=request.relevance,
        action_id="api.link_source",
        idempotency_key=idempotency_key,
        reason=request.reason,
    )
    return LinkSourceResponse(created=created)


@router.get("/{thing_id}/tasks", response_model=list[TaskResponse])
async def list_tasks(
    thing_id: UUID,
    container: ContainerDependency,
    user_id: CurrentUserId,
) -> list[TaskResponse]:
    tasks = await container.personal_state.get_tasks(user_id=user_id, thing_id=thing_id)
    return [TaskResponse.from_dto(task) for task in tasks]


@router.post(
    "/{thing_id}/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    thing_id: UUID,
    request: CreateTaskRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> TaskResponse:
    task = await container.personal_state.create_task(
        user_id=user_id,
        thing_id=thing_id,
        title=request.title,
        action_id="api.create_task",
        idempotency_key=idempotency_key,
        reason="User created Task through Product API.",
    )
    return TaskResponse.from_dto(task)
