from laoshiren.domain.files.entities import File, FileAssetStatus, FileMediaKind
from laoshiren.domain.sources.entities import Source, SourceType


def media_kind_from_source_type(source_type: SourceType) -> FileMediaKind:
    if source_type is SourceType.IMAGE:
        return FileMediaKind.IMAGE
    if source_type in {SourceType.PDF, SourceType.WORD, SourceType.PPT}:
        return FileMediaKind.DOCUMENT
    if source_type is SourceType.AUDIO:
        return FileMediaKind.AUDIO
    return FileMediaKind.OTHER


def file_from_source(source: Source) -> File:
    return File(
        id=source.id,
        owner_user_id=source.user_id,
        original_filename=source.title,
        validated_mime_type=source.mime_type,
        media_kind=media_kind_from_source_type(source.source_type),
        size_bytes=source.size,
        content_sha256=source.content_hash,
        storage_key=source.object_key,
        idempotency_key=source.idempotency_key,
        asset_status=(
            FileAssetStatus.DELETED if source.deleted_at is not None else FileAssetStatus.ACTIVE
        ),
        deleted_at=source.deleted_at,
        created_at=source.created_at,
    )
