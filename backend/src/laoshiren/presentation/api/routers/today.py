from datetime import UTC, datetime

from fastapi import APIRouter

from laoshiren.presentation.api.dependencies import ContainerDependency, CurrentUserId
from laoshiren.presentation.api.schemas.today import TodayResponse

router = APIRouter(prefix="/today", tags=["today"])


@router.get("", response_model=TodayResponse)
async def get_today(
    container: ContainerDependency,
    user_id: CurrentUserId,
) -> TodayResponse:
    now = datetime.now(UTC)
    overview = await container.personal_state.get_state_overview(user_id=user_id, now=now)
    attention = await container.attention.get_candidates(user_id=user_id, now=now, limit=5)
    return TodayResponse.from_sources(attention=attention, overview=overview, now=now)
