from uuid import UUID

from fastapi import APIRouter, status

from laoshiren.presentation.api.dependencies import ContainerDependency, CurrentUserId
from laoshiren.presentation.api.routers.auth import to_device_response
from laoshiren.presentation.api.schemas.identity import (
    DeviceRegisterRequest,
    DeviceResponse,
    PushTokenRequest,
)

router = APIRouter(tags=["devices"])


@router.post("/devices/register", response_model=DeviceResponse)
async def register_device(
    payload: DeviceRegisterRequest,
    user_id: CurrentUserId,
    container: ContainerDependency,
) -> DeviceResponse:
    device = await container.identity.register_device(
        user_id=user_id,
        device_id=payload.device_id,
        timezone_name=payload.timezone,
        platform=payload.platform,
    )
    return to_device_response(device)


@router.put("/devices/{device_id}/push-token", status_code=status.HTTP_204_NO_CONTENT)
async def upsert_push_token(
    device_id: UUID,
    payload: PushTokenRequest,
    user_id: CurrentUserId,
    container: ContainerDependency,
) -> None:
    await container.identity.upsert_push_token(
        user_id=user_id,
        device_id=device_id,
        push_token=payload.push_token,
        provider=payload.provider,
    )


@router.delete("/devices/{device_id}/push-token", status_code=status.HTTP_204_NO_CONTENT)
async def delete_push_token(
    device_id: UUID,
    user_id: CurrentUserId,
    container: ContainerDependency,
) -> None:
    await container.identity.delete_push_token(user_id=user_id, device_id=device_id)
