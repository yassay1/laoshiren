"""Typed EvidenceRef helpers for File and Web provenance."""

from uuid import UUID

from laoshiren.domain.evidence.value_objects import EvidenceRef, EvidenceSourceKind
from laoshiren.domain.files.entities import File, FileAssetStatus


def file_evidence_ref(
    file_id: UUID,
    *,
    locator: dict[str, object] | None = None,
) -> EvidenceRef:
    return EvidenceRef(
        source_kind=EvidenceSourceKind.FILE,
        source_id=file_id,
        locator=locator,
    )


def web_evidence_ref(
    observation_id: UUID,
    *,
    locator: dict[str, object] | None = None,
) -> EvidenceRef:
    return EvidenceRef(
        source_kind=EvidenceSourceKind.WEB,
        source_id=observation_id,
        locator=locator,
    )


def resolve_file_evidence_status(file: File | None) -> str:
    if file is None:
        return "MISSING"
    if file.asset_status is FileAssetStatus.DELETED:
        return "DELETED" if file.purged_at is None else "PURGED"
    return "ACTIVE"
