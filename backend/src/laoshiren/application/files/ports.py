from typing import Protocol
from uuid import UUID

from laoshiren.domain.files.entities import (
    File,
    FileProcessingGeneration,
    MessageAttachment,
    RetrievalSegment,
    WebObservation,
)


class FileRepository(Protocol):
    async def add(self, file: File) -> None: ...

    async def get(self, *, user_id: UUID, file_id: UUID) -> File | None: ...

    async def get_including_deleted(self, *, user_id: UUID, file_id: UUID) -> File | None: ...

    async def mark_deleted(self, *, user_id: UUID, file_id: UUID) -> File | None: ...

    async def add_generation(self, generation: FileProcessingGeneration) -> None: ...

    async def get_active_generation(self, *, file_id: UUID) -> FileProcessingGeneration | None: ...

    async def retire_active_generations(self, *, file_id: UUID) -> None: ...

    async def replace_segments(
        self, *, generation_id: UUID, segments: list[RetrievalSegment]
    ) -> None: ...

    async def purge_segments_for_file(self, *, file_id: UUID) -> None: ...

    async def search_for_user(
        self,
        *,
        user_id: UUID,
        query: str,
        thing_id: UUID | None,
        limit: int,
    ) -> list[File]: ...

    async def list_segments(
        self,
        *,
        user_id: UUID,
        file_id: UUID,
        limit: int,
        query_embedding: list[float] | None = None,
        query_text: str | None = None,
    ) -> list[RetrievalSegment]: ...

    async def add_web_observation(self, observation: WebObservation) -> None: ...

    async def get_web_observation(
        self, *, user_id: UUID, observation_id: UUID
    ) -> WebObservation | None: ...

    async def add_message_attachment(self, attachment: MessageAttachment) -> None: ...

    async def list_attachments_for_message(
        self, *, message_id: UUID
    ) -> list[MessageAttachment]: ...

    async def mark_purged(self, *, user_id: UUID, file_id: UUID) -> File | None: ...

    async def list_storage_keys(self) -> list[str]: ...

    async def list_orphan_candidates(self, *, limit: int) -> list[File]: ...
