from uuid import UUID

from fastapi import APIRouter

from laoshiren.presentation.api.dependencies import (
    ContainerDependency,
    CurrentUserId,
    IdempotencyKey,
)
from laoshiren.presentation.api.schemas.personal_state import (
    MutationResponse,
    UpdateTaskRequest,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


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
