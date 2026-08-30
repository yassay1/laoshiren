"""Load current Message attachments for invocation-time context."""

from uuid import UUID

from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork


async def load_message_attachment_context(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    message_id: UUID,
    max_preview_characters: int = 2_000,
) -> list[dict[str, str]]:
    attachments = await uow.files.list_attachments_for_message(message_id=message_id)
    context: list[dict[str, str]] = []
    for attachment in attachments:
        file = await uow.files.get(user_id=user_id, file_id=attachment.file_id)
        if file is None:
            continue
        source = await uow.sources.get(user_id=user_id, source_id=attachment.file_id)
        preview = ""
        if source is not None and source.extracted_text:
            preview = source.extracted_text[:max_preview_characters]
        context.append(
            {
                "file_id": str(file.id),
                "message_id": str(attachment.message_id),
                "attachment_order": str(attachment.attachment_order),
                "title": file.original_filename or "",
                "mime_type": file.validated_mime_type,
                "media_kind": file.media_kind.value,
                "preview": preview,
            }
        )
    return context
