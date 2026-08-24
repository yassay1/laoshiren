from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from laoshiren.presentation.api.dependencies import ContainerDependency

router = APIRouter(tags=["system"])


@router.get("/health", summary="Check backend health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


class OperationalStatusResponse(BaseModel):
    status: str
    checked_at: datetime
    backlogs: dict[str, int]


@router.get("/health/ready", response_model=OperationalStatusResponse)
async def readiness(container: ContainerDependency) -> OperationalStatusResponse:
    value = await container.operational_status.get_status()
    return OperationalStatusResponse(
        status=value.status,
        checked_at=value.checked_at,
        backlogs=value.backlogs,
    )
