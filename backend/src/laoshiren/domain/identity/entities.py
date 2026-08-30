from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from laoshiren.domain.identity.value_objects import DevicePlatform, UserStatus


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class User:
    id: UUID = field(default_factory=uuid4)
    status: UserStatus = UserStatus.ACTIVE
    external_subject: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def begin_deletion(self) -> None:
        if self.status is UserStatus.DELETED:
            return
        self.status = UserStatus.DELETING
        self.updated_at = utc_now()

    def mark_deleted(self) -> None:
        self.status = UserStatus.DELETED
        self.updated_at = utc_now()


@dataclass(slots=True)
class Device:
    user_id: UUID
    timezone_name: str
    id: UUID = field(default_factory=uuid4)
    platform: DevicePlatform = DevicePlatform.HARMONYOS
    active: bool = True
    last_seen_at: datetime = field(default_factory=utc_now)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def touch(self, *, timezone_name: str | None = None) -> None:
        if timezone_name is not None:
            self.timezone_name = timezone_name
        self.last_seen_at = utc_now()
        self.updated_at = utc_now()

    def deactivate(self) -> None:
        self.active = False
        self.updated_at = utc_now()


@dataclass(slots=True)
class BusinessSession:
    user_id: UUID
    token_hash: str
    expires_at: datetime
    device_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    revoked_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)

    def revoke(self) -> None:
        self.revoked_at = utc_now()

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > utc_now()
