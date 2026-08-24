from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, UploadFile, status

from laoshiren.domain.sources.entities import SourceOrigin
from laoshiren.presentation.api.dependencies import (
    ContainerDependency,
    CurrentUserId,
    IdempotencyKey,
)
from laoshiren.presentation.api.schemas.sources import SourceResponse

router = APIRouter(prefix="/sources", tags=["sources"])


async def upload_chunks(
    upload: UploadFile, *, chunk_size: int = 1024 * 1024
) -> AsyncIterator[bytes]:
    while chunk := await upload.read(chunk_size):
        yield chunk


@router.post("", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def upload_source(
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
    file: Annotated[UploadFile, File()],
    origin: Annotated[SourceOrigin, Form()] = SourceOrigin.UPLOAD,
) -> SourceResponse:
    try:
        source = await container.sources.upload(
            user_id=user_id,
            filename=file.filename or "",
            mime_type=file.content_type or "application/octet-stream",
            chunks=upload_chunks(file),
            idempotency_key=idempotency_key,
            origin=origin,
        )
        return SourceResponse.from_dto(source)
    finally:
        await file.close()


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: UUID,
    container: ContainerDependency,
    user_id: CurrentUserId,
) -> SourceResponse:
    source = await container.sources.get(user_id=user_id, source_id=source_id)
    return SourceResponse.from_dto(source)
