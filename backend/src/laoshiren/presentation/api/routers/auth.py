from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from laoshiren.application.identity.dto import DeviceDTO
from laoshiren.domain.personal_state.exceptions import EntityNotFound, InvalidStateTransition
from laoshiren.presentation.api.dependencies import ContainerDependency, CurrentUserId
from laoshiren.presentation.api.schemas.identity import (
    DeviceResponse,
    HuaweiLoginRequest,
    LoginResponse,
    UserProfileResponse,
)

router = APIRouter(tags=["auth"])


@router.post("/auth/huawei/login", response_model=LoginResponse)
async def huawei_login(
    payload: HuaweiLoginRequest,
    container: ContainerDependency,
) -> LoginResponse:
    result = await container.identity.huawei_login(
        id_token=payload.id_token,
        device_id=payload.device_id,
        timezone_name=payload.timezone,
        platform=payload.platform,
    )
    return LoginResponse(
        access_token=result.access_token,
        user_id=result.user_id,
        expires_at=result.expires_at,
    )


@router.post("/auth/refresh", response_model=LoginResponse)
async def refresh_session(
    container: ContainerDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> LoginResponse:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token.",
        )
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token.",
        )
    try:
        result = await container.identity.refresh_session(access_token=token)
    except (EntityNotFound, InvalidStateTransition) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    return LoginResponse(
        access_token=result.access_token,
        user_id=result.user_id,
        expires_at=result.expires_at,
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    user_id: CurrentUserId,
    container: ContainerDependency,
    authorization: Annotated[str, Header()],
) -> None:
    token = authorization.removeprefix("Bearer ").strip()
    await container.identity.logout(user_id=user_id, access_token=token)


@router.get("/me", response_model=UserProfileResponse)
async def get_me(user_id: CurrentUserId, container: ContainerDependency) -> UserProfileResponse:
    profile = await container.identity.get_profile(user_id=user_id)
    return UserProfileResponse(
        user_id=profile.user_id,
        status=profile.status,
        created_at=profile.created_at,
    )


@router.delete("/me", status_code=status.HTTP_202_ACCEPTED)
async def delete_me(user_id: CurrentUserId, container: ContainerDependency) -> None:
    await container.identity.request_account_deletion(user_id=user_id)


def to_device_response(device: DeviceDTO) -> DeviceResponse:
    return DeviceResponse(
        device_id=device.device_id,
        platform=device.platform,
        timezone=device.timezone_name,
        active=device.active,
        last_seen_at=device.last_seen_at,
    )
