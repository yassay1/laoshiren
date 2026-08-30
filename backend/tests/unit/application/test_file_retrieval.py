from uuid import uuid4

from laoshiren.application.files.retrieval import build_search_result_item, segment_to_context_chunk
from laoshiren.domain.files.entities import (
    File,
    FileMediaKind,
    RepresentationKind,
    RetrievalSegment,
)
from laoshiren.domain.sources.entities import Source, SourceOrigin, SourceType


def test_segment_to_context_chunk_maps_locator_fields() -> None:
    segment = RetrievalSegment(
        file_id=uuid4(),
        generation_id=uuid4(),
        segment_order=2,
        representation_kind=RepresentationKind.PAGE_TEXT,
        content="hello",
        locator={"char_start": 10, "char_end": 15, "page_number": 3},
    )
    chunk = segment_to_context_chunk(segment)
    assert chunk.ordinal == 2
    assert chunk.page_number == 3
    assert chunk.char_start == 10


def test_build_search_result_item_prefers_v2_segments() -> None:
    file_id = uuid4()
    file = File(
        id=file_id,
        owner_user_id=uuid4(),
        validated_mime_type="application/pdf",
        media_kind=FileMediaKind.DOCUMENT,
        size_bytes=1,
        content_sha256="hash",
        storage_key="k",
        idempotency_key="idem",
        original_filename="a.pdf",
    )
    source = Source(
        id=file_id,
        user_id=file.owner_user_id,
        source_type=SourceType.PDF,
        origin=SourceOrigin.UPLOAD,
        title="a.pdf",
        mime_type="application/pdf",
        object_key="k",
        content_hash="hash",
        size=1,
        idempotency_key="idem",
    )
    segment = RetrievalSegment(
        file_id=file_id,
        generation_id=uuid4(),
        segment_order=0,
        representation_kind=RepresentationKind.TEXT_SPAN,
        content="policy text",
    )
    item = build_search_result_item(
        file=file,
        source=source,
        segments=[segment],
        legacy_chunks=[],
    )
    assert item["retrieval_backend"] == "v2"
    assert item["fragments"][0]["segment_id"] == str(segment.id)
