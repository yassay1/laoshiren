from uuid import UUID

from fastapi import APIRouter

from laoshiren.presentation.api.dependencies import (
    ContainerDependency,
    CurrentUserId,
    IdempotencyKey,
)
from laoshiren.presentation.api.schemas.personal_state import (
    CreateTaskRequest,
    MutationResponse,
    TaskResponse,
    UpdateTaskRequest,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskResponse])
async def list_standalone_tasks(
    container: ContainerDependency, user_id: CurrentUserId
) -> list[TaskResponse]:
    tasks = await container.personal_state.get_standalone_tasks(user_id=user_id)
    return [TaskResponse.from_dto(task) for task in tasks]


@router.post("", response_model=TaskResponse, status_code=201)
async def create_standalone_task(
    request: CreateTaskRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> TaskResponse:
    task = await container.personal_state.create_task(
        user_id=user_id,
        thing_id=None,
        title=request.title,
        due_at=request.due_at,
        recurrence_interval_days=request.recurrence_interval_days,
        action_id="api.create_standalone_task",
        idempotency_key=idempotency_key,
        reason="User created standalone Task through Product API.",
    )
    return TaskResponse.from_dto(task)


@router.patch("/{task_id}", response_model=MutationResponse)
async def update_task(
    task_id: UUID,
    request: UpdateTaskRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> MutationResponse:
    result = await container.personal_state.transition_task(
        user_id=user_id,
        task_id=task_id,
        target_status=request.status,
        expected_version=request.expected_version,
        action_id="api.transition_task",
        idempotency_key=idempotency_key,
        reason=request.reason,
    )
    return MutationResponse(
        mutation_id=result.mutation_id,
        target_id=result.target_id,
        target_version=result.target_version,
        replayed=result.replayed,
    )
