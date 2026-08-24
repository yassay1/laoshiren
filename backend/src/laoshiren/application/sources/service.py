import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import PurePath
from uuid import UUID, uuid4

from laoshiren.application.ai.ports import EmbeddingProvider, EmbeddingProviderError
from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.application.sources.dto import (
    SourceContextChunkDTO,
    SourceDTO,
    SourceProcessingJobDTO,
)
from laoshiren.application.sources.ports import (
    ObjectStorage,
    ParsedSourceContent,
    ParsedSourcePage,
    SourceParser,
    SourceParsingError,
)
from laoshiren.domain.personal_state.entities import StateMutation, TimelineEvent, utc_now
from laoshiren.domain.personal_state.exceptions import EntityNotFound
from laoshiren.domain.sources.entities import (
    Source,
    SourceChunk,
    SourceOrigin,
    SourceRelationType,
    SourceType,
    ThingSource,
)

UnitOfWorkFactory = Callable[[], PersonalStateUnitOfWork]

ALLOWED_UPLOADS: dict[str, tuple[SourceType, set[str], tuple[bytes, ...]]] = {
    ".pdf": (SourceType.PDF, {"application/pdf"}, (b"%PDF-",)),
    ".png": (SourceType.IMAGE, {"image/png"}, (b"\x89PNG\r\n\x1a\n",)),
    ".jpg": (SourceType.IMAGE, {"image/jpeg"}, (b"\xff\xd8\xff",)),
    ".jpeg": (SourceType.IMAGE, {"image/jpeg"}, (b"\xff\xd8\xff",)),
    ".docx": (
        SourceType.WORD,
        {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        (b"PK\x03\x04",),
    ),
    ".pptx": (
        SourceType.PPT,
        {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
        (b"PK\x03\x04",),
    ),
    ".mp3": (SourceType.AUDIO, {"audio/mpeg"}, (b"ID3", b"\xff\xfb", b"\xff\xf3")),
    ".txt": (SourceType.OTHER, {"text/plain"}, ()),
    ".md": (SourceType.OTHER, {"text/markdown", "text/plain"}, ()),
}
PROCESSABLE_MIME_TYPES = ("text/plain", "text/markdown", "application/pdf")


def build_source_chunks(
    *, source_id: UUID, text: str, chunk_characters: int = 2_000, overlap: int = 200
) -> list[SourceChunk]:
    if chunk_characters <= 0 or not 0 <= overlap < chunk_characters:
        raise ValueError("Source chunk and overlap limits are invalid.")
    chunks: list[SourceChunk] = []
    start = 0
    ordinal = 0
    while start < len(text):
        hard_end = min(start + chunk_characters, len(text))
        end = hard_end
        if hard_end < len(text):
            paragraph_end = text.rfind("\n\n", start, hard_end)
            if paragraph_end > start + chunk_characters // 2:
                end = paragraph_end
        content = text[start:end].strip()
        if content:
            chunks.append(
                SourceChunk(
                    source_id=source_id,
                    ordinal=ordinal,
                    content=content,
                    char_start=start,
                    char_end=end,
                    metadata={"evidence_type": "TEXT_SPAN"},
                )
            )
            ordinal += 1
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def build_source_chunks_from_content(
    *,
    source_id: UUID,
    content: ParsedSourceContent,
    chunk_characters: int = 2_000,
    overlap: int = 200,
) -> list[SourceChunk]:
    if not content.pages:
        return build_source_chunks(
            source_id=source_id,
            text=content.text,
            chunk_characters=chunk_characters,
            overlap=overlap,
        )
    chunks: list[SourceChunk] = []
    base_offset = 0
    for page in content.pages:
        page_chunks = build_source_chunks(
            source_id=source_id,
            text=page.text,
            chunk_characters=chunk_characters,
            overlap=overlap,
        )
        for chunk in page_chunks:
            chunks.append(
                replace(
                    chunk,
                    ordinal=len(chunks),
                    char_start=base_offset + chunk.char_start,
                    char_end=base_offset + chunk.char_end,
                    page_number=page.page_number,
                    metadata={
                        **chunk.metadata,
                        "page_number": page.page_number,
                    },
                )
            )
        base_offset += len(page.text) + 2
    return chunks


def to_source_dto(source: Source, *, replayed: bool = False) -> SourceDTO:
    return SourceDTO(
        id=source.id,
        user_id=source.user_id,
        source_type=source.source_type,
        origin=source.origin,
        title=source.title,
        mime_type=source.mime_type,
        size=source.size,
        content_hash=source.content_hash,
        processing_status=source.processing_status,
        extracted_text=source.extracted_text,
        processing_error=source.processing_error,
        processed_at=source.processed_at,
        captured_at=source.captured_at,
        metadata=source.metadata,
        created_at=source.created_at,
        replayed=replayed,
    )


class SourceApplicationService:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        storage: ObjectStorage,
        *,
        max_upload_bytes: int,
        parser: SourceParser | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        parse_timeout_seconds: float = 30.0,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._storage = storage
        self._max_upload_bytes = max_upload_bytes
        self._parser = parser
        self._embedding_provider = embedding_provider
        if parse_timeout_seconds <= 0:
            raise ValueError("Source parse timeout must be positive.")
        self._parse_timeout_seconds = parse_timeout_seconds

    async def upload(
        self,
        *,
        user_id: UUID,
        filename: str,
        mime_type: str,
        chunks: AsyncIterator[bytes],
        idempotency_key: str,
        origin: SourceOrigin = SourceOrigin.UPLOAD,
    ) -> SourceDTO:
        safe_name = PurePath(filename).name
        extension = PurePath(safe_name).suffix.lower()
        rule = ALLOWED_UPLOADS.get(extension)
        if not safe_name or rule is None:
            raise ValueError("Unsupported or missing file extension.")
        source_type, allowed_mimes, signatures = rule
        if mime_type not in allowed_mimes:
            raise ValueError("File MIME type does not match its extension.")

        async with self._unit_of_work_factory() as unit_of_work:
            previous = await unit_of_work.sources.get_by_idempotency(
                user_id=user_id, key=idempotency_key
            )
            if previous is not None:
                return to_source_dto(previous, replayed=True)

        first_chunk: bytes | None = None

        async def checked_chunks() -> AsyncIterator[bytes]:
            nonlocal first_chunk
            total = 0
            async for chunk in chunks:
                if not chunk:
                    continue
                if first_chunk is None:
                    first_chunk = chunk
                    if signatures and not any(
                        chunk.startswith(signature) for signature in signatures
                    ):
                        raise ValueError("File signature does not match its declared type.")
                total += len(chunk)
                if total > self._max_upload_bytes:
                    raise ValueError("File exceeds the configured upload size limit.")
                yield chunk
            if first_chunk is None:
                raise ValueError("Uploaded file is empty.")

        object_key = f"{user_id}/{uuid4().hex}{extension}"
        try:
            size, content_hash = await self._storage.put(
                object_key=object_key, chunks=checked_chunks()
            )
            source = Source(
                user_id=user_id,
                source_type=source_type,
                origin=origin,
                title=safe_name,
                mime_type=mime_type,
                object_key=object_key,
                content_hash=content_hash,
                size=size,
                idempotency_key=idempotency_key,
            )
            async with self._unit_of_work_factory() as unit_of_work:
                await unit_of_work.users.ensure_exists(user_id)
                await unit_of_work.sources.add(source)
                await unit_of_work.commit()
            return to_source_dto(source)
        except Exception:
            await self._storage.delete(object_key=object_key)
            raise

    async def claim_next_processing(
        self,
        *,
        owner: str,
        lease_seconds: float,
        max_attempts: int,
    ) -> SourceProcessingJobDTO | None:
        if not owner.strip() or lease_seconds <= 0 or max_attempts <= 0:
            raise ValueError("Source processing claim settings must be positive.")
        now = datetime.now(UTC)
        async with self._unit_of_work_factory() as unit_of_work:
            source = await unit_of_work.sources.claim_next_processing(
                owner=owner,
                now=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                supported_mime_types=PROCESSABLE_MIME_TYPES,
                max_attempts=max_attempts,
            )
            if source is None:
                await unit_of_work.rollback()
                return None
            await unit_of_work.commit()
            return SourceProcessingJobDTO(
                id=source.id,
                user_id=source.user_id,
                title=source.title,
                mime_type=source.mime_type,
                object_key=source.object_key,
                attempt_count=source.processing_attempt_count,
            )

    async def extract_claimed_content(
        self, job: SourceProcessingJobDTO
    ) -> ParsedSourceContent:
        if self._parser is None:
            raise RuntimeError("No Source parser is configured.")
        content = await self._storage.read(object_key=job.object_key)
        try:
            return await asyncio.wait_for(
                self._parser.parse(
                    filename=job.title,
                    mime_type=job.mime_type,
                    content=content,
                ),
                timeout=self._parse_timeout_seconds,
            )
        except TimeoutError as exception:
            raise SourceParsingError("Source parsing exceeded its time limit.") from exception

    async def renew_processing_lease(
        self,
        *,
        source_id: UUID,
        owner: str,
        lease_seconds: float,
    ) -> bool:
        now = datetime.now(UTC)
        async with self._unit_of_work_factory() as unit_of_work:
            renewed = await unit_of_work.sources.renew_processing_lease(
                source_id=source_id,
                owner=owner,
                now=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
            )
            if renewed:
                await unit_of_work.commit()
            else:
                await unit_of_work.rollback()
            return renewed

    async def complete_processing(
        self,
        *,
        source_id: UUID,
        owner: str,
        parsed_content: ParsedSourceContent,
    ) -> bool:
        clean_text = parsed_content.text.strip()
        if not clean_text:
            raise ValueError("Extracted Source text cannot be empty.")
        normalized = ParsedSourceContent(
            text=clean_text,
            pages=tuple(
                ParsedSourcePage(page_number=page.page_number, text=page.text.strip())
                for page in parsed_content.pages
                if page.text.strip()
            ),
        )
        chunks = build_source_chunks_from_content(
            source_id=source_id, content=normalized
        )
        if self._embedding_provider is not None and chunks:
            try:
                embeddings = await self._embedding_provider.embed_many(
                    [chunk.content for chunk in chunks]
                )
            except EmbeddingProviderError:
                embeddings = []
            if len(embeddings) == len(chunks):
                chunks = [
                    replace(chunk, embedding=embedding)
                    for chunk, embedding in zip(chunks, embeddings, strict=True)
                ]
        async with self._unit_of_work_factory() as unit_of_work:
            completed = await unit_of_work.sources.complete_processing(
                source_id=source_id,
                owner=owner,
                extracted_text=clean_text,
                chunks=chunks,
                now=datetime.now(UTC),
            )
            if completed:
                await unit_of_work.commit()
            else:
                await unit_of_work.rollback()
            return completed

    async def get_context_chunks(
        self,
        *,
        user_id: UUID,
        source_id: UUID,
        max_chunks: int = 8,
        max_characters: int = 12_000,
        query: str | None = None,
    ) -> list[SourceContextChunkDTO]:
        if max_chunks <= 0 or max_characters <= 0:
            raise ValueError("Source context limits must be positive.")
        async with self._unit_of_work_factory() as unit_of_work:
            source = await unit_of_work.sources.get(
                user_id=user_id, source_id=source_id
            )
            if source is None:
                raise EntityNotFound("Source was not found.")
            query_text = query.strip() if query and query.strip() else None
            query_embedding: list[float] | None = None
            if query_text is not None and self._embedding_provider is not None:
                with suppress(EmbeddingProviderError):
                    query_embedding = await self._embedding_provider.embed(query_text)
            chunks = await unit_of_work.sources.list_chunks(
                user_id=user_id,
                source_id=source_id,
                limit=max_chunks,
                query_embedding=query_embedding,
                query_text=query_text if query_embedding is None else None,
            )
            if not chunks and query_text is not None:
                chunks = await unit_of_work.sources.list_chunks(
                    user_id=user_id, source_id=source_id, limit=max_chunks
                )
        result: list[SourceContextChunkDTO] = []
        remaining = max_characters
        for chunk in chunks:
            if remaining <= 0:
                break
            content = chunk.content[:remaining]
            result.append(
                SourceContextChunkDTO(
                    id=chunk.id,
                    source_id=chunk.source_id,
                    ordinal=chunk.ordinal,
                    content=content,
                    char_start=chunk.char_start,
                    char_end=min(chunk.char_start + len(content), chunk.char_end),
                    page_number=chunk.page_number,
                )
            )
            remaining -= len(content)
        return result

    async def fail_processing(
        self,
        *,
        source_id: UUID,
        owner: str,
        error_code: str,
        retry_delay_seconds: float | None,
    ) -> bool:
        now = datetime.now(UTC)
        retry_at = (
            now + timedelta(seconds=retry_delay_seconds)
            if retry_delay_seconds is not None
            else None
        )
        async with self._unit_of_work_factory() as unit_of_work:
            failed = await unit_of_work.sources.fail_processing(
                source_id=source_id,
                owner=owner,
                error_code=error_code,
                now=now,
                retry_at=retry_at,
            )
            if failed:
                await unit_of_work.commit()
            else:
                await unit_of_work.rollback()
            return failed

    async def get(self, *, user_id: UUID, source_id: UUID) -> SourceDTO:
        async with self._unit_of_work_factory() as unit_of_work:
            source = await unit_of_work.sources.get(user_id=user_id, source_id=source_id)
            if source is None:
                raise EntityNotFound("Source was not found.")
            return to_source_dto(source)

    async def list_for_thing(self, *, user_id: UUID, thing_id: UUID) -> list[SourceDTO]:
        async with self._unit_of_work_factory() as unit_of_work:
            thing = await unit_of_work.things.get(user_id=user_id, thing_id=thing_id)
            if thing is None:
                raise EntityNotFound("Thing was not found.")
            sources = await unit_of_work.sources.list_for_thing(
                user_id=user_id, thing_id=thing_id
            )
            return [to_source_dto(source) for source in sources]

    async def link_to_thing(
        self,
        *,
        user_id: UUID,
        thing_id: UUID,
        source_id: UUID,
        relation_type: SourceRelationType,
        relevance: float,
        action_id: str,
        idempotency_key: str,
        reason: str,
    ) -> bool:
        if not 0 <= relevance <= 1:
            raise ValueError("Source relevance must be between 0 and 1.")
        async with self._unit_of_work_factory() as unit_of_work:
            previous = await unit_of_work.audit.get_mutation(
                user_id=user_id, idempotency_key=idempotency_key
            )
            if previous is not None:
                return False
            thing = await unit_of_work.things.get(user_id=user_id, thing_id=thing_id)
            source = await unit_of_work.sources.get(user_id=user_id, source_id=source_id)
            if thing is None:
                raise EntityNotFound("Thing was not found.")
            if source is None:
                raise EntityNotFound("Source was not found.")
            created = await unit_of_work.sources.add_relation(
                ThingSource(
                    thing_id=thing_id,
                    source_id=source_id,
                    relation_type=relation_type,
                    relevance=relevance,
                )
            )
            mutation = StateMutation(
                user_id=user_id,
                thing_id=thing_id,
                action_id=action_id,
                mutation_type="SOURCE_LINKED",
                target_type="SOURCE",
                target_id=source_id,
                after={
                    "relation_type": relation_type.value,
                    "relevance": relevance,
                    "created": created,
                },
                reason=reason,
                source_id=source_id,
                idempotency_key=idempotency_key,
            )
            await unit_of_work.audit.add_mutation(mutation)
            await unit_of_work.flush()
            if created:
                await unit_of_work.audit.add_timeline_event(
                    TimelineEvent(
                        user_id=user_id,
                        thing_id=thing_id,
                        event_type="SOURCE_ADDED",
                        title=f"添加来源：{source.title}",
                        occurred_at=utc_now(),
                        source_id=source_id,
                        mutation_id=mutation.id,
                    )
                )
            await unit_of_work.commit()
            return created
