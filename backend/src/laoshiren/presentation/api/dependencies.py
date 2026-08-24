from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status

from laoshiren.bootstrap import Container


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDependency = Annotated[Container, Depends(get_container)]


def get_current_user_id(
    container: ContainerDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> UUID:
    expected = f"Bearer {container.settings.dev_auth_token}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token.",
        )
    return UUID(container.settings.dev_user_id)


CurrentUserId = Annotated[UUID, Depends(get_current_user_id)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)]
