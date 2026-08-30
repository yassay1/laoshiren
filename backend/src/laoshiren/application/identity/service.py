from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from laoshiren.application.identity.dto import DeviceDTO, LoginResultDTO, UserProfileDTO
from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.domain.automations.entities import AutomationStatus, PushEndpoint
from laoshiren.domain.identity.entities import BusinessSession, Device, User
from laoshiren.domain.identity.value_objects import DevicePlatform, UserStatus
from laoshiren.domain.personal_state.exceptions import EntityNotFound, InvalidStateTransition
from laoshiren.domain.runtime.entities import DurableJob, DurableJobKind
from laoshiren.infrastructure.auth.huawei_stub import resolve_external_subject
from laoshiren.infrastructure.auth.session_tokens import hash_access_token, issue_access_token

UnitOfWorkFactory = Callable[[], PersonalStateUnitOfWork]


class IdentityApplicationService:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        app_env: str,
        session_ttl_hours: int = 24 * 30,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._app_env = app_env
        self._session_ttl_hours = session_ttl_hours

    async def huawei_login(
        self,
        *,
        id_token: str,
        device_id: UUID | None = None,
        timezone_name: str | None = None,
        platform: DevicePlatform = DevicePlatform.HARMONYOS,
    ) -> LoginResultDTO:
        external_subject = resolve_external_subject(id_token=id_token, app_env=self._app_env)
        async with self._unit_of_work_factory() as uow:
            user = await uow.users.get_by_external_subject(external_subject=external_subject)
            if user is None:
                user = User(external_subject=external_subject)
                await uow.users.add(user)
                await uow.flush()
            elif user.status is UserStatus.DELETED:
                raise InvalidStateTransition("Account has been deleted.")
            elif user.status is UserStatus.DELETING:
                raise InvalidStateTransition("Account deletion is in progress.")

            bound_device_id = device_id
            if device_id is not None and timezone_name is not None:
                await self._register_device_locked(
                    uow,
                    user_id=user.id,
                    device_id=device_id,
                    timezone_name=timezone_name,
                    platform=platform,
                )

            access_token = issue_access_token()
            session = BusinessSession(
                user_id=user.id,
                device_id=bound_device_id,
                token_hash=hash_access_token(access_token),
                expires_at=datetime.now(UTC) + timedelta(hours=self._session_ttl_hours),
            )
            await uow.business_sessions.add(session)
            await uow.commit()
            return LoginResultDTO(
                access_token=access_token,
                user_id=user.id,
                expires_at=session.expires_at,
            )

    async def refresh_session(self, *, access_token: str) -> LoginResultDTO:
        token_hash = hash_access_token(access_token)
        async with self._unit_of_work_factory() as uow:
            session = await uow.business_sessions.get_by_token_hash(token_hash=token_hash)
            if session is None or session.revoked_at is not None:
                raise EntityNotFound("Session was not found.")
            user = await uow.users.get(user_id=session.user_id)
            if user is None or user.status is not UserStatus.ACTIVE:
                raise InvalidStateTransition("Account is not active.")

            session.revoke()
            await uow.business_sessions.update(session)

            new_access_token = issue_access_token()
            new_session = BusinessSession(
                user_id=session.user_id,
                device_id=session.device_id,
                token_hash=hash_access_token(new_access_token),
                expires_at=datetime.now(UTC) + timedelta(hours=self._session_ttl_hours),
            )
            await uow.business_sessions.add(new_session)
            await uow.commit()
            return LoginResultDTO(
                access_token=new_access_token,
                user_id=session.user_id,
                expires_at=new_session.expires_at,
            )

    async def logout(self, *, user_id: UUID, access_token: str) -> None:
        token_hash = hash_access_token(access_token)
        async with self._unit_of_work_factory() as uow:
            session = await uow.business_sessions.get_by_token_hash(token_hash=token_hash)
            if session is None or session.user_id != user_id:
                raise EntityNotFound("Session was not found.")
            session.revoke()
            await uow.business_sessions.update(session)
            if session.device_id is not None:
                await uow.push_endpoints.invalidate_for_device(
                    user_id=user_id,
                    device_id=session.device_id,
                )
            await uow.commit()

    async def get_profile(self, *, user_id: UUID) -> UserProfileDTO:
        async with self._unit_of_work_factory() as uow:
            user = await uow.users.get(user_id=user_id)
            if user is None:
                raise EntityNotFound("User was not found.")
            return UserProfileDTO(
                user_id=user.id,
                status=user.status,
                created_at=user.created_at,
            )

    async def register_device(
        self,
        *,
        user_id: UUID,
        device_id: UUID,
        timezone_name: str,
        platform: DevicePlatform = DevicePlatform.HARMONYOS,
    ) -> DeviceDTO:
        clean_timezone = timezone_name.strip()
        if not clean_timezone:
            raise ValueError("timezone must not be empty.")
        async with self._unit_of_work_factory() as uow:
            user = await uow.users.get(user_id=user_id)
            if user is None or user.status is not UserStatus.ACTIVE:
                raise InvalidStateTransition("Account is not active.")
            device = await self._register_device_locked(
                uow,
                user_id=user_id,
                device_id=device_id,
                timezone_name=clean_timezone,
                platform=platform,
            )
            await uow.commit()
            return device

    async def upsert_push_token(
        self,
        *,
        user_id: UUID,
        device_id: UUID,
        push_token: str,
        provider: str = "HUAWEI",
    ) -> None:
        clean_token = push_token.strip()
        if not clean_token:
            raise ValueError("push_token must not be empty.")
        now = datetime.now(UTC)
        async with self._unit_of_work_factory() as uow:
            device = await uow.devices.get_for_user(user_id=user_id, device_id=device_id)
            if device is None:
                raise EntityNotFound("Device was not found.")
            endpoint = PushEndpoint(
                user_id=user_id,
                device_id=device_id,
                provider=provider,
                push_token=clean_token,
                active=True,
                notifications_enabled=True,
                last_registered_at=now,
                invalidated_at=None,
            )
            await uow.push_endpoints.upsert(endpoint)
            await uow.commit()

    async def delete_push_token(self, *, user_id: UUID, device_id: UUID) -> None:
        async with self._unit_of_work_factory() as uow:
            await uow.push_endpoints.invalidate_for_device(user_id=user_id, device_id=device_id)
            await uow.commit()

    async def request_account_deletion(self, *, user_id: UUID) -> None:
        async with self._unit_of_work_factory() as uow:
            user = await uow.users.get(user_id=user_id)
            if user is None:
                raise EntityNotFound("User was not found.")
            if user.status is UserStatus.DELETED:
                return
            user.begin_deletion()
            await uow.users.update(user)
            dedupe_key = f"account-deletion:{user_id}"
            existing = await uow.durable_jobs.get_by_dedupe_key(
                user_id=user_id,
                dedupe_key=dedupe_key,
            )
            if existing is None:
                await uow.durable_jobs.add(
                    DurableJob(
                        user_id=user_id,
                        kind=DurableJobKind.ACCOUNT_DELETION,
                        dedupe_key=dedupe_key,
                        payload={"user_id": str(user_id)},
                        available_at=datetime.now(UTC),
                    )
                )
            await uow.commit()

    async def _register_device_locked(
        self,
        uow: PersonalStateUnitOfWork,
        *,
        user_id: UUID,
        device_id: UUID,
        timezone_name: str,
        platform: DevicePlatform,
    ) -> DeviceDTO:
        existing = await uow.devices.get(device_id=device_id)
        if existing is not None and existing.user_id != user_id:
            raise InvalidStateTransition("Device is owned by another user.")
        device = existing or Device(user_id=user_id, id=device_id, timezone_name=timezone_name)
        device.user_id = user_id
        device.platform = platform
        device.active = True
        device.touch(timezone_name=timezone_name)
        await uow.devices.upsert(device)
        return DeviceDTO(
            device_id=device.id,
            platform=device.platform,
            timezone_name=device.timezone_name,
            active=device.active,
            last_seen_at=device.last_seen_at,
        )


async def apply_account_deletion(uow: PersonalStateUnitOfWork, *, user_id: UUID) -> None:
    user = await uow.users.get(user_id=user_id)
    if user is None:
        return
    if user.status is UserStatus.DELETED:
        return
    if user.status is not UserStatus.DELETING:
        user.begin_deletion()

    automations = await uow.automations.list_for_user(user_id=user_id, limit=500)
    for automation in automations:
        if automation.status is AutomationStatus.ACTIVE:
            expected_version = automation.version
            automation.cancel()
            await uow.automations.update(automation, expected_version=expected_version)

    await uow.push_endpoints.invalidate_for_user(user_id=user_id)
    await uow.devices.deactivate_for_user(user_id=user_id)
    await uow.business_sessions.revoke_for_user(user_id=user_id)
    user.mark_deleted()
    await uow.users.update(user)
