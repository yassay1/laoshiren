from uuid import UUID

from fastapi import APIRouter

from laoshiren.presentation.api.dependencies import (
    ContainerDependency,
    CurrentUserId,
    IdempotencyKey,
)
from laoshiren.presentation.api.schemas.personal_state import (
    MutationResponse,
    ResolveBlockerRequest,
    UpdateDateRequest,
)

router = APIRouter(tags=["personal-state"])


@router.patch("/thing-dates/{date_id}", response_model=MutationResponse)
async def update_date(
    date_id: UUID,
    request: UpdateDateRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> MutationResponse:
    result = await container.personal_state.update_date(
        user_id=user_id,
        date_id=date_id,
        value=request.value,
        timezone_name=request.timezone,
        precision=request.precision,
        certainty=request.certainty,
        is_primary=request.is_primary,
        expected_version=request.expected_version,
        expected_thing_version=request.expected_thing_version,
        action_id="api.update_date",
        idempotency_key=idempotency_key,
        reason=request.reason,
    )
    return MutationResponse(
        mutation_id=result.mutation_id,
        target_id=result.target_id,
        target_version=result.target_version,
        replayed=result.replayed,
    )


@router.post("/blockers/{blocker_id}/resolve", response_model=MutationResponse)
async def resolve_blocker(
    blocker_id: UUID,
    request: ResolveBlockerRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> MutationResponse:
    result = await container.personal_state.resolve_blocker(
        user_id=user_id,
        blocker_id=blocker_id,
        expected_version=request.expected_version,
        action_id="api.resolve_blocker",
        idempotency_key=idempotency_key,
        reason=request.reason,
    )
    return MutationResponse(
        mutation_id=result.mutation_id,
        target_id=result.target_id,
        target_version=result.target_version,
        replayed=result.replayed,
    )
