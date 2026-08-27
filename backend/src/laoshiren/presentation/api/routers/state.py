from typing import Annotated

from fastapi import APIRouter, Query

from laoshiren.presentation.api.dependencies import ContainerDependency, CurrentUserId
from laoshiren.presentation.api.schemas.state import StateOverviewResponse

router = APIRouter(prefix="/state", tags=["state"])


@router.get("/overview", response_model=StateOverviewResponse)
async def get_state_overview(
    container: ContainerDependency,
    user_id: CurrentUserId,
    upcoming_days: Annotated[int, Query(ge=1, le=30)] = 7,
    upcoming_limit: Annotated[int, Query(ge=1, le=20)] = 8,
    blocked_limit: Annotated[int, Query(ge=1, le=20)] = 5,
    active_limit: Annotated[int, Query(ge=1, le=20)] = 8,
    recent_limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> StateOverviewResponse:
    overview = await container.personal_state.get_state_overview(
        user_id=user_id,
        upcoming_days=upcoming_days,
        upcoming_limit=upcoming_limit,
        blocked_limit=blocked_limit,
        active_limit=active_limit,
        recent_limit=recent_limit,
    )
    return StateOverviewResponse.from_dto(overview)
