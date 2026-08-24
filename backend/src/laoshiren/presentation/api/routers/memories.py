from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from laoshiren.domain.memories.entities import MemoryType
from laoshiren.presentation.api.dependencies import (
    ContainerDependency,
    CurrentUserId,
    IdempotencyKey,
)
from laoshiren.presentation.api.schemas.memories import (
    CreateMemoryRequest,
    MemoryResponse,
    UpdateMemoryRequest,
)

router = APIRouter(prefix="/memories", tags=["memories"])


@router.get("", response_model=list[MemoryResponse])
async def search_memories(
    container: ContainerDependency,
    user_id: CurrentUserId,
    q: str | None = None,
    memory_type: MemoryType | None = None,
    thing_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[MemoryResponse]:
    memories = await container.memories.search(
        user_id=user_id,
        query=q,
        memory_type=memory_type,
        thing_id=thing_id,
        limit=limit,
    )
    return [MemoryResponse.from_dto(memory) for memory in memories]


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    request: CreateMemoryRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> MemoryResponse:
    memory = await container.memories.create(
        user_id=user_id,
        memory_type=request.memory_type,
        content=request.content,
        summary=request.summary,
        importance=request.importance,
        confidence=request.confidence,
        idempotency_key=idempotency_key,
        thing_id=request.thing_id,
        source_ids=request.source_ids,
        valid_from=request.valid_from,
        valid_until=request.valid_until,
        profile_key=request.profile_key,
    )
    return MemoryResponse.from_dto(memory)


@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: UUID,
    container: ContainerDependency,
    user_id: CurrentUserId,
) -> MemoryResponse:
    memory = await container.memories.get(user_id=user_id, memory_id=memory_id)
    return MemoryResponse.from_dto(memory)


@router.patch("/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: UUID,
    request: UpdateMemoryRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> MemoryResponse:
    memory = await container.memories.update(
        user_id=user_id,
        memory_id=memory_id,
        expected_version=request.expected_version,
        content=request.content,
        summary=request.summary,
        importance=request.importance,
        confidence=request.confidence,
        idempotency_key=idempotency_key,
        supersede=request.supersede,
    )
    return MemoryResponse.from_dto(memory)


@router.delete("/{memory_id}", response_model=MemoryResponse)
async def delete_memory(
    memory_id: UUID,
    expected_version: Annotated[int, Query(ge=1)],
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> MemoryResponse:
    memory = await container.memories.update(
        user_id=user_id,
        memory_id=memory_id,
        expected_version=expected_version,
        content=None,
        summary=None,
        importance=None,
        confidence=None,
        idempotency_key=idempotency_key,
        delete=True,
    )
    return MemoryResponse.from_dto(memory)
