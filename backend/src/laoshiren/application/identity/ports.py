from typing import Protocol
from uuid import UUID

from laoshiren.application.identity.dto import HuaweiAccountIdentityDTO
from laoshiren.domain.identity.entities import BusinessSession, Device


class HuaweiAccountError(RuntimeError):
    """Base error exposed by a Huawei Account infrastructure adapter."""


class HuaweiAuthorizationCodeRejected(HuaweiAccountError):
    """The authorization code is invalid, expired, or already consumed."""


class HuaweiAccountUnavailable(HuaweiAccountError):
    """Huawei Account could not complete a trustworthy identity exchange."""


class HuaweiAccountClient(Protocol):
    async def exchange_authorization_code(
        self,
        *,
        authorization_code: str,
    ) -> HuaweiAccountIdentityDTO: ...


class DeviceRepository(Protocol):
    async def get(self, *, device_id: UUID) -> Device | None: ...

    async def get_for_user(self, *, user_id: UUID, device_id: UUID) -> Device | None: ...

    async def upsert(self, device: Device) -> None: ...

    async def deactivate_for_user(self, *, user_id: UUID) -> None: ...


class BusinessSessionRepository(Protocol):
    async def add(self, session: BusinessSession) -> None: ...

    async def get_by_token_hash(self, *, token_hash: str) -> BusinessSession | None: ...

    async def revoke_for_user(self, *, user_id: UUID) -> None: ...

    async def update(self, session: BusinessSession) -> None: ...
