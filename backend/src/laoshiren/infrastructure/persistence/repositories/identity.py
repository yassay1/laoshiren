from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from laoshiren.domain.identity.entities import BusinessSession, Device, User
from laoshiren.infrastructure.persistence.orm.personal_state import (
    BusinessSessionORM,
    DeviceORM,
    UserORM,
)


def user_to_domain(model: UserORM) -> User:
    return User(
        id=model.id,
        status=model.status,
        external_subject=model.external_subject,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def device_to_domain(model: DeviceORM) -> Device:
    return Device(
        id=model.id,
        user_id=model.user_id,
        platform=model.platform,
        timezone_name=model.timezone_name,
        active=model.active,
        last_seen_at=model.last_seen_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def session_to_domain(model: BusinessSessionORM) -> BusinessSession:
    return BusinessSession(
        id=model.id,
        user_id=model.user_id,
        device_id=model.device_id,
        token_hash=model.token_hash,
        expires_at=model.expires_at,
        revoked_at=model.revoked_at,
        created_at=model.created_at,
    )


class SqlAlchemyIdentityUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_exists(self, user_id: UUID) -> None:
        await self._session.execute(
            insert(UserORM).values(id=user_id).on_conflict_do_nothing(index_elements=["id"])
        )

    async def get(self, *, user_id: UUID) -> User | None:
        model = await self._session.scalar(select(UserORM).where(UserORM.id == user_id))
        return user_to_domain(model) if model is not None else None

    async def get_by_external_subject(self, *, external_subject: str) -> User | None:
        model = await self._session.scalar(
            select(UserORM).where(UserORM.external_subject == external_subject)
        )
        return user_to_domain(model) if model is not None else None

    async def add(self, user: User) -> None:
        self._session.add(
            UserORM(
                id=user.id,
                status=user.status,
                external_subject=user.external_subject,
                created_at=user.created_at,
                updated_at=user.updated_at,
            )
        )

    async def update(self, user: User) -> None:
        await self._session.execute(
            update(UserORM)
            .where(UserORM.id == user.id)
            .values(
                status=user.status,
                external_subject=user.external_subject,
                updated_at=user.updated_at,
            )
        )


class SqlAlchemyDeviceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, *, device_id: UUID) -> Device | None:
        model = await self._session.scalar(select(DeviceORM).where(DeviceORM.id == device_id))
        return device_to_domain(model) if model is not None else None

    async def get_for_user(self, *, user_id: UUID, device_id: UUID) -> Device | None:
        model = await self._session.scalar(
            select(DeviceORM).where(DeviceORM.id == device_id, DeviceORM.user_id == user_id)
        )
        return device_to_domain(model) if model is not None else None

    async def upsert(self, device: Device) -> None:
        await self._session.execute(
            insert(DeviceORM)
            .values(
                id=device.id,
                user_id=device.user_id,
                platform=device.platform,
                timezone_name=device.timezone_name,
                active=device.active,
                last_seen_at=device.last_seen_at,
                created_at=device.created_at,
                updated_at=device.updated_at,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "timezone_name": device.timezone_name,
                    "active": device.active,
                    "last_seen_at": device.last_seen_at,
                    "updated_at": device.updated_at,
                },
            )
        )

    async def deactivate_for_user(self, *, user_id: UUID) -> None:
        now = datetime.now(UTC)
        await self._session.execute(
            update(DeviceORM)
            .where(DeviceORM.user_id == user_id, DeviceORM.active.is_(True))
            .values(active=False, updated_at=now)
        )


class SqlAlchemyBusinessSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, session: BusinessSession) -> None:
        self._session.add(
            BusinessSessionORM(
                id=session.id,
                user_id=session.user_id,
                device_id=session.device_id,
                token_hash=session.token_hash,
                expires_at=session.expires_at,
                revoked_at=session.revoked_at,
                created_at=session.created_at,
            )
        )

    async def get_by_token_hash(self, *, token_hash: str) -> BusinessSession | None:
        model = await self._session.scalar(
            select(BusinessSessionORM).where(BusinessSessionORM.token_hash == token_hash)
        )
        return session_to_domain(model) if model is not None else None

    async def revoke_for_user(self, *, user_id: UUID) -> None:
        now = datetime.now(UTC)
        await self._session.execute(
            update(BusinessSessionORM)
            .where(
                BusinessSessionORM.user_id == user_id,
                BusinessSessionORM.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    async def update(self, session: BusinessSession) -> None:
        await self._session.execute(
            update(BusinessSessionORM)
            .where(BusinessSessionORM.id == session.id)
            .values(revoked_at=session.revoked_at)
        )
