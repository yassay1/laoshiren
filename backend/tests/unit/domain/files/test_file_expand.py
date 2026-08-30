from uuid import uuid4

from laoshiren.application.files.mappers import file_from_source, media_kind_from_source_type
from laoshiren.domain.evidence.value_objects import EvidenceRef, EvidenceSourceKind
from laoshiren.domain.files.entities import FileMediaKind
from laoshiren.domain.sources.entities import Source, SourceOrigin, SourceType


def test_media_kind_from_source_type_maps_document_types() -> None:
    assert media_kind_from_source_type(SourceType.PDF) is FileMediaKind.DOCUMENT
    assert media_kind_from_source_type(SourceType.IMAGE) is FileMediaKind.IMAGE


def test_file_from_source_preserves_stable_identity() -> None:
    source = Source(
        id=uuid4(),
        user_id=uuid4(),
        source_type=SourceType.PDF,
        origin=SourceOrigin.UPLOAD,
        title="report.pdf",
        mime_type="application/pdf",
        object_key="user/report.pdf",
        content_hash="abc",
        size=42,
        idempotency_key="upload-1",
    )
    file = file_from_source(source)
    assert file.id == source.id
    assert file.storage_key == source.object_key
    assert file.original_filename == "report.pdf"


def test_evidence_ref_round_trips_json() -> None:
    ref = EvidenceRef(
        source_kind=EvidenceSourceKind.FILE,
        source_id=uuid4(),
        locator={"page_number": 2},
    )
    restored = EvidenceRef.from_json(ref.to_json())
    assert restored == ref
