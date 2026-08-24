from collections.abc import AsyncIterator
from typing import Protocol
from uuid import UUID

from laoshiren.domain.sources.entities import Source, SourceRelationType, ThingSource


class SourceRepository(Protocol):
    async def add(self, source: Source) -> None: ...

    async def get(self, *, user_id: UUID, source_id: UUID) -> Source | None: ...

    async def get_by_idempotency(self, *, user_id: UUID, key: str) -> Source | None: ...

    async def add_relation(self, relation: ThingSource) -> bool: ...

    async def list_for_thing(self, *, user_id: UUID, thing_id: UUID) -> list[Source]: ...


class ObjectStorage(Protocol):
    async def put(self, *, object_key: str, chunks: AsyncIterator[bytes]) -> tuple[int, str]: ...

    async def delete(self, *, object_key: str) -> None: ...
    async def read(self, *, object_key: str) -> bytes: ...


class SourceParser(Protocol):
    async def parse(self, *, filename: str, mime_type: str, content: bytes) -> str: ...


class SourceParsingError(ValueError):
    """A supported Source could not be converted into text."""


class SourceLinkRequest(Protocol):
    relation_type: SourceRelationType
    relevance: float
