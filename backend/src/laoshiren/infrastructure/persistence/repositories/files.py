from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from laoshiren.domain.files.entities import (
    File,
    FileAssetStatus,
    FileProcessingGeneration,
    GenerationStatus,
    MessageAttachment,
    RetrievalSegment,
    WebObservation,
)
from laoshiren.infrastructure.persistence.orm.files import (
    FileORM,
    FileProcessingGenerationORM,
    MessageAttachmentORM,
    RetrievalSegmentORM,
    WebObservationORM,
)
from laoshiren.infrastructure.persistence.orm.personal_state import ThingSourceORM


def file_to_domain(model: FileORM) -> File:
    return File(
        id=model.id,
        owner_user_id=model.owner_user_id,
        original_filename=model.original_filename,
        validated_mime_type=model.validated_mime_type,
        media_kind=model.media_kind,
        size_bytes=model.size_bytes,
        content_sha256=model.content_sha256,
        storage_key=model.storage_key,
        asset_status=model.asset_status,
        version=model.version,
        idempotency_key=model.idempotency_key,
        deleted_at=model.deleted_at,
        purged_at=model.purged_at,
        created_at=model.created_at,
    )


def generation_to_domain(model: FileProcessingGenerationORM) -> FileProcessingGeneration:
    return FileProcessingGeneration(
        id=model.id,
        file_id=model.file_id,
        profile_name=model.profile_name,
        parser_version=model.parser_version,
        chunk_version=model.chunk_version,
        embedding_model_version=model.embedding_model_version,
        status=model.status,
        is_active=model.is_active,
        created_at=model.created_at,
        ready_at=model.ready_at,
        retired_at=model.retired_at,
    )


def observation_to_domain(model: WebObservationORM) -> WebObservation:
    return WebObservation(
        id=model.id,
        owner_user_id=model.owner_user_id,
        requested_url=model.requested_url,
        final_url=model.final_url,
        title=model.title,
        content_type=model.content_type,
        observed_at=model.observed_at,
        retrieval_method=model.retrieval_method,
        bounded_excerpt=model.bounded_excerpt,
        locator=model.locator,
        content_hash=model.content_hash,
        created_at=model.created_at,
    )


def segment_to_domain(model: RetrievalSegmentORM) -> RetrievalSegment:
    return RetrievalSegment(
        id=model.id,
        file_id=model.file_id,
        generation_id=model.generation_id,
        segment_order=model.segment_order,
        representation_kind=model.representation_kind,
        content=model.content,
        locator=model.locator,
        embedding=list(model.embedding) if model.embedding is not None else None,
        created_at=model.created_at,
    )


class SqlAlchemyFileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, file: File) -> None:
        self._session.add(
            FileORM(
                id=file.id,
                owner_user_id=file.owner_user_id,
                original_filename=file.original_filename,
                validated_mime_type=file.validated_mime_type,
                media_kind=file.media_kind,
                size_bytes=file.size_bytes,
                content_sha256=file.content_sha256,
                storage_key=file.storage_key,
                asset_status=file.asset_status,
                version=file.version,
                idempotency_key=file.idempotency_key,
                deleted_at=file.deleted_at,
                purged_at=file.purged_at,
                created_at=file.created_at,
            )
        )

    async def get(self, *, user_id: UUID, file_id: UUID) -> File | None:
        model = await self._session.scalar(
            select(FileORM).where(
                FileORM.id == file_id,
                FileORM.owner_user_id == user_id,
                FileORM.deleted_at.is_(None),
            )
        )
        return file_to_domain(model) if model is not None else None

    async def get_including_deleted(self, *, user_id: UUID, file_id: UUID) -> File | None:
        model = await self._session.scalar(
            select(FileORM).where(FileORM.id == file_id, FileORM.owner_user_id == user_id)
        )
        return file_to_domain(model) if model is not None else None

    async def mark_deleted(self, *, user_id: UUID, file_id: UUID) -> File | None:
        now = datetime.now(UTC)
        model = await self._session.scalar(
            update(FileORM)
            .where(
                FileORM.id == file_id,
                FileORM.owner_user_id == user_id,
                FileORM.deleted_at.is_(None),
            )
            .values(
                deleted_at=now,
                asset_status=FileAssetStatus.DELETED,
            )
            .returning(FileORM)
        )
        return file_to_domain(model) if model is not None else None

    async def add_generation(self, generation: FileProcessingGeneration) -> None:
        self._session.add(
            FileProcessingGenerationORM(
                id=generation.id,
                file_id=generation.file_id,
                profile_name=generation.profile_name,
                parser_version=generation.parser_version,
                chunk_version=generation.chunk_version,
                embedding_model_version=generation.embedding_model_version,
                status=generation.status,
                is_active=generation.is_active,
                created_at=generation.created_at,
                ready_at=generation.ready_at,
                retired_at=generation.retired_at,
            )
        )

    async def get_active_generation(self, *, file_id: UUID) -> FileProcessingGeneration | None:
        model = await self._session.scalar(
            select(FileProcessingGenerationORM).where(
                FileProcessingGenerationORM.file_id == file_id,
                FileProcessingGenerationORM.is_active.is_(True),
            )
        )
        return generation_to_domain(model) if model is not None else None

    async def retire_active_generations(self, *, file_id: UUID) -> None:
        now = datetime.now(UTC)
        await self._session.execute(
            update(FileProcessingGenerationORM)
            .where(
                FileProcessingGenerationORM.file_id == file_id,
                FileProcessingGenerationORM.is_active.is_(True),
            )
            .values(is_active=False, status=GenerationStatus.RETIRED, retired_at=now)
        )

    async def replace_segments(
        self, *, generation_id: UUID, segments: list[RetrievalSegment]
    ) -> None:
        await self._session.execute(
            delete(RetrievalSegmentORM).where(RetrievalSegmentORM.generation_id == generation_id)
        )
        for segment in segments:
            self._session.add(
                RetrievalSegmentORM(
                    id=segment.id,
                    file_id=segment.file_id,
                    generation_id=segment.generation_id,
                    segment_order=segment.segment_order,
                    representation_kind=segment.representation_kind,
                    content=segment.content,
                    locator=segment.locator,
                    embedding=segment.embedding,
                    created_at=segment.created_at,
                )
            )

    async def purge_segments_for_file(self, *, file_id: UUID) -> None:
        await self._session.execute(
            delete(RetrievalSegmentORM).where(RetrievalSegmentORM.file_id == file_id)
        )

    async def search_for_user(
        self,
        *,
        user_id: UUID,
        query: str,
        thing_id: UUID | None,
        limit: int,
    ) -> list[File]:
        statement = select(FileORM).where(
            FileORM.owner_user_id == user_id,
            FileORM.deleted_at.is_(None),
            FileORM.asset_status == FileAssetStatus.ACTIVE,
        )
        if thing_id is not None:
            statement = statement.join(
                ThingSourceORM, ThingSourceORM.source_id == FileORM.id
            ).where(ThingSourceORM.thing_id == thing_id)
        normalized = query.strip()
        if normalized:
            segment_match = exists(
                select(1)
                .select_from(RetrievalSegmentORM)
                .join(
                    FileProcessingGenerationORM,
                    FileProcessingGenerationORM.id == RetrievalSegmentORM.generation_id,
                )
                .where(
                    RetrievalSegmentORM.file_id == FileORM.id,
                    FileProcessingGenerationORM.is_active.is_(True),
                    RetrievalSegmentORM.content.ilike(f"%{normalized}%"),
                )
            )
            statement = statement.where(
                or_(
                    FileORM.original_filename.ilike(f"%{normalized}%"),
                    segment_match,
                )
            )
        statement = statement.order_by(FileORM.created_at.desc(), FileORM.id.desc()).limit(
            limit
        )
        models = (await self._session.scalars(statement)).all()
        return [file_to_domain(model) for model in models]

    async def list_segments(
        self,
        *,
        user_id: UUID,
        file_id: UUID,
        limit: int,
        query_embedding: list[float] | None = None,
        query_text: str | None = None,
    ) -> list[RetrievalSegment]:
        statement = (
            select(RetrievalSegmentORM)
            .join(FileORM, FileORM.id == RetrievalSegmentORM.file_id)
            .join(
                FileProcessingGenerationORM,
                FileProcessingGenerationORM.id == RetrievalSegmentORM.generation_id,
            )
            .where(
                RetrievalSegmentORM.file_id == file_id,
                FileORM.owner_user_id == user_id,
                FileORM.deleted_at.is_(None),
                FileProcessingGenerationORM.is_active.is_(True),
            )
        )
        if query_embedding is not None:
            statement = statement.where(RetrievalSegmentORM.embedding.is_not(None)).order_by(
                RetrievalSegmentORM.embedding.cosine_distance(query_embedding),
                RetrievalSegmentORM.segment_order,
            )
        elif query_text is not None:
            statement = statement.where(
                RetrievalSegmentORM.content.ilike(f"%{query_text}%")
            ).order_by(RetrievalSegmentORM.segment_order)
        else:
            statement = statement.order_by(RetrievalSegmentORM.segment_order)
        models = (await self._session.scalars(statement.limit(limit))).all()
        return [segment_to_domain(model) for model in models]

    async def add_web_observation(self, observation: WebObservation) -> None:
        self._session.add(
            WebObservationORM(
                id=observation.id,
                owner_user_id=observation.owner_user_id,
                requested_url=observation.requested_url,
                final_url=observation.final_url,
                title=observation.title,
                content_type=observation.content_type,
                observed_at=observation.observed_at,
                retrieval_method=observation.retrieval_method,
                bounded_excerpt=observation.bounded_excerpt,
                locator=observation.locator,
                content_hash=observation.content_hash,
                created_at=observation.created_at,
            )
        )

    async def get_web_observation(
        self, *, user_id: UUID, observation_id: UUID
    ) -> WebObservation | None:
        model = await self._session.scalar(
            select(WebObservationORM).where(
                WebObservationORM.id == observation_id,
                WebObservationORM.owner_user_id == user_id,
            )
        )
        return observation_to_domain(model) if model is not None else None

    async def add_message_attachment(self, attachment: MessageAttachment) -> None:
        self._session.add(
            MessageAttachmentORM(
                id=attachment.id,
                message_id=attachment.message_id,
                file_id=attachment.file_id,
                attachment_order=attachment.attachment_order,
                created_at=attachment.created_at,
            )
        )

    async def list_attachments_for_message(
        self, *, message_id: UUID
    ) -> list[MessageAttachment]:
        models = (
            await self._session.scalars(
                select(MessageAttachmentORM)
                .where(MessageAttachmentORM.message_id == message_id)
                .order_by(MessageAttachmentORM.attachment_order)
            )
        ).all()
        return [
            MessageAttachment(
                id=model.id,
                message_id=model.message_id,
                file_id=model.file_id,
                attachment_order=model.attachment_order,
                created_at=model.created_at,
            )
            for model in models
        ]

    async def mark_purged(self, *, user_id: UUID, file_id: UUID) -> File | None:
        now = datetime.now(UTC)
        model = await self._session.scalar(
            update(FileORM)
            .where(
                FileORM.id == file_id,
                FileORM.owner_user_id == user_id,
                FileORM.deleted_at.is_not(None),
                FileORM.purged_at.is_(None),
            )
            .values(purged_at=now)
            .returning(FileORM)
        )
        return file_to_domain(model) if model is not None else None

    async def list_storage_keys(self) -> list[str]:
        models = (await self._session.scalars(select(FileORM.storage_key))).all()
        return list(models)

    async def list_orphan_candidates(self, *, limit: int) -> list[File]:
        attachment_exists = exists(
            select(1).where(MessageAttachmentORM.file_id == FileORM.id)
        )
        thing_link_exists = exists(
            select(1).where(ThingSourceORM.source_id == FileORM.id)
        )
        statement = (
            select(FileORM)
            .where(
                FileORM.deleted_at.is_(None),
                FileORM.asset_status == FileAssetStatus.ACTIVE,
                ~attachment_exists,
                ~thing_link_exists,
            )
            .order_by(FileORM.created_at)
            .limit(limit)
        )
        models = (await self._session.scalars(statement)).all()
        return [file_to_domain(model) for model in models]
