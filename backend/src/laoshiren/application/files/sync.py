"""Mirror legacy Source rows into V2.2 File tables inside an open Unit of Work."""

from uuid import UUID

from laoshiren.application.files.mappers import file_from_source
from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.domain.files.entities import (
    FileProcessingGeneration,
    GenerationStatus,
    RepresentationKind,
    RetrievalSegment,
)
from laoshiren.domain.sources.entities import Source, SourceChunk

DEFAULT_PROFILE_NAME = "default"


async def mirror_source_upload(uow: PersonalStateUnitOfWork, source: Source) -> None:
    existing = await uow.files.get_including_deleted(
        user_id=source.user_id, file_id=source.id
    )
    if existing is not None:
        return
    await uow.files.add(file_from_source(source))


async def mirror_source_delete(
    uow: PersonalStateUnitOfWork, *, user_id: UUID, file_id: UUID
) -> None:
    await uow.files.mark_deleted(user_id=user_id, file_id=file_id)
    await uow.files.purge_segments_for_file(file_id=file_id)


async def mirror_processing_complete(
    uow: PersonalStateUnitOfWork,
    *,
    source: Source,
    chunks: list[SourceChunk],
    parser_version: str,
    chunk_version: str,
    embedding_model_version: str | None,
) -> None:
    file = await uow.files.get_including_deleted(user_id=source.user_id, file_id=source.id)
    if file is None:
        await uow.files.add(file_from_source(source))
    await uow.files.retire_active_generations(file_id=source.id)
    generation = FileProcessingGeneration(
        file_id=source.id,
        profile_name=DEFAULT_PROFILE_NAME,
        parser_version=parser_version,
        chunk_version=chunk_version,
        embedding_model_version=embedding_model_version,
        status=GenerationStatus.READY,
        is_active=True,
    )
    generation.mark_ready()
    await uow.files.add_generation(generation)
    segments = [
        RetrievalSegment(
            file_id=source.id,
            generation_id=generation.id,
            segment_order=chunk.ordinal,
            representation_kind=(
                RepresentationKind.PAGE_TEXT
                if chunk.page_number is not None
                else RepresentationKind.TEXT_SPAN
            ),
            content=chunk.content,
            locator={
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                **({"page_number": chunk.page_number} if chunk.page_number is not None else {}),
                **chunk.metadata,
            },
            embedding=chunk.embedding,
        )
        for chunk in chunks
    ]
    await uow.files.replace_segments(generation_id=generation.id, segments=segments)
