from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from laoshiren.domain.identity.value_objects import DevicePlatform, UserStatus


class HuaweiLoginRequest(BaseModel):
    id_token: str = Field(min_length=1)
    device_id: UUID | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    platform: DevicePlatform = DevicePlatform.HARMONYOS


class LoginResponse(BaseModel):
    access_token: str
    user_id: UUID
    expires_at: datetime


class UserProfileResponse(BaseModel):
    user_id: UUID
    status: UserStatus
    created_at: datetime


class DeviceRegisterRequest(BaseModel):
    device_id: UUID
    timezone: str = Field(min_length=1, max_length=100)
    platform: DevicePlatform = DevicePlatform.HARMONYOS


class DeviceResponse(BaseModel):
    device_id: UUID
    platform: DevicePlatform
    timezone: str
    active: bool
    last_seen_at: datetime


class PushTokenRequest(BaseModel):
    push_token: str = Field(min_length=1, max_length=500)
    provider: str = Field(default="HUAWEI", min_length=1, max_length=50)
