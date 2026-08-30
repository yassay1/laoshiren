"""V2 retrieval read path with legacy Source fallback."""

from uuid import UUID

from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.application.sources.dto import SourceContextChunkDTO
from laoshiren.domain.files.entities import File, RetrievalSegment
from laoshiren.domain.sources.entities import Source, SourceChunk


def segment_to_context_chunk(segment: RetrievalSegment) -> SourceContextChunkDTO:
    locator = segment.locator
    char_start_raw = locator.get("char_start", 0)
    char_end_raw = locator.get("char_end", len(segment.content))
    char_start = char_start_raw if isinstance(char_start_raw, int) else 0
    char_end = char_end_raw if isinstance(char_end_raw, int) else len(segment.content)
    page_number = locator.get("page_number")
    page_number_int = page_number if isinstance(page_number, int) else None
    return SourceContextChunkDTO(
        id=segment.id,
        source_id=segment.file_id,
        ordinal=segment.segment_order,
        content=segment.content,
        char_start=char_start,
        char_end=char_end,
        page_number=page_number_int,
    )


async def list_inspect_segments(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    file_id: UUID,
    max_chunks: int,
    query_embedding: list[float] | None = None,
    query_text: str | None = None,
) -> list[RetrievalSegment]:
    segments = await uow.files.list_segments(
        user_id=user_id,
        file_id=file_id,
        limit=max_chunks,
        query_embedding=query_embedding,
        query_text=query_text,
    )
    if segments or query_text is None:
        return segments
    return await uow.files.list_segments(
        user_id=user_id,
        file_id=file_id,
        limit=max_chunks,
    )


async def search_active_files(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    query: str,
    thing_id: UUID | None,
    limit: int,
) -> list[File]:
    return await uow.files.search_for_user(
        user_id=user_id,
        query=query,
        thing_id=thing_id,
        limit=limit,
    )


def build_search_result_item(
    *,
    file: File,
    source: Source | None,
    segments: list[RetrievalSegment],
    legacy_chunks: list[SourceChunk],
) -> dict[str, object]:
    title = file.original_filename or (source.title if source is not None else "file")
    mime_type = file.validated_mime_type
    processing_status = source.processing_status.value if source is not None else "READY"
    fragments: list[dict[str, object]] = []
    if segments:
        for segment in segments[:3]:
            fragments.append(
                {
                    "segment_id": str(segment.id),
                    "ordinal": segment.segment_order,
                    "preview": segment.content[:400],
                }
            )
    else:
        for chunk in legacy_chunks[:3]:
            fragments.append(
                {
                    "chunk_id": str(chunk.id),
                    "ordinal": chunk.ordinal,
                    "preview": chunk.content[:400],
                }
            )
    return {
        "file_id": str(file.id),
        "title": title,
        "mime_type": mime_type,
        "processing_status": processing_status,
        "fragments": fragments,
        "retrieval_backend": "v2" if segments else "legacy",
    }
