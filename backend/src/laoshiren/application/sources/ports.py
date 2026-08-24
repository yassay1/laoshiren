from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol
from uuid import UUID

from laoshiren.domain.sources.entities import (
    Source,
    SourceChunk,
    SourceRelationType,
    ThingSource,
)


class SourceRepository(Protocol):
    async def add(self, source: Source) -> None: ...

    async def get(self, *, user_id: UUID, source_id: UUID) -> Source | None: ...

    async def get_by_idempotency(self, *, user_id: UUID, key: str) -> Source | None: ...

    async def add_relation(self, relation: ThingSource) -> bool: ...

    async def list_for_thing(self, *, user_id: UUID, thing_id: UUID) -> list[Source]: ...

    async def claim_next_processing(
        self,
        *,
        owner: str,
        now: datetime,
        lease_expires_at: datetime,
        supported_mime_types: tuple[str, ...],
        max_attempts: int,
    ) -> Source | None: ...

    async def renew_processing_lease(
        self,
        *,
        source_id: UUID,
        owner: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool: ...

    async def complete_processing(
        self,
        *,
        source_id: UUID,
        owner: str,
        extracted_text: str,
        chunks: list[SourceChunk],
        now: datetime,
    ) -> bool: ...

    async def fail_processing(
        self,
        *,
        source_id: UUID,
        owner: str,
        error_code: str,
        now: datetime,
        retry_at: datetime | None,
    ) -> bool: ...

    async def list_chunks(
        self, *, user_id: UUID, source_id: UUID, limit: int
    ) -> list[SourceChunk]: ...


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
