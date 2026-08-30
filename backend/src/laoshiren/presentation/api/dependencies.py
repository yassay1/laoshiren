from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status

from laoshiren.bootstrap import Container
from laoshiren.domain.identity.value_objects import UserStatus
from laoshiren.infrastructure.auth.session_tokens import hash_access_token


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDependency = Annotated[Container, Depends(get_container)]


async def get_current_user_id(
    container: ContainerDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> UUID:
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

    if (
        container.settings.app_env == "development"
        and token == container.settings.dev_auth_token
    ):
        return UUID(container.settings.dev_user_id)

    token_hash = hash_access_token(token)
    async with container.database.personal_state_unit_of_work() as unit_of_work:
        session = await unit_of_work.business_sessions.get_by_token_hash(token_hash=token_hash)
        if session is None or not session.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session.",
            )
        user = await unit_of_work.users.get(user_id=session.user_id)
        if user is None or user.status is not UserStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is not active.",
            )
        return session.user_id


CurrentUserId = Annotated[UUID, Depends(get_current_user_id)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)]
