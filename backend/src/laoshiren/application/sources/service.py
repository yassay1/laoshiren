from collections.abc import AsyncIterator, Callable
from pathlib import PurePath
from uuid import UUID, uuid4

from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.application.sources.dto import SourceDTO
from laoshiren.application.sources.ports import ObjectStorage
from laoshiren.domain.personal_state.entities import StateMutation, TimelineEvent, utc_now
from laoshiren.domain.personal_state.exceptions import EntityNotFound
from laoshiren.domain.sources.entities import (
    Source,
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
}


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
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._storage = storage
        self._max_upload_bytes = max_upload_bytes

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
                    if not any(chunk.startswith(signature) for signature in signatures):
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
