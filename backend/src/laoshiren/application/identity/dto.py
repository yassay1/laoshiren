from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from laoshiren.domain.identity.value_objects import DevicePlatform, UserStatus


@dataclass(frozen=True, slots=True)
class LoginResultDTO:
    access_token: str
    user_id: UUID
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class UserProfileDTO:
    user_id: UUID
    status: UserStatus
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DeviceDTO:
    device_id: UUID
    platform: DevicePlatform
    timezone_name: str
    active: bool
    last_seen_at: datetime
