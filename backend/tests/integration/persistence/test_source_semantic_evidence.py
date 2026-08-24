import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from laoshiren.application.sources.ports import ParsedSourceContent, ParsedSourcePage
from laoshiren.application.sources.service import SourceApplicationService
from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


class UnusedStorage:
    async def put(
        self, *, object_key: str, chunks: AsyncIterator[bytes]
    ) -> tuple[int, str]:
        raise AssertionError("not used")

    async def read(self, *, object_key: str) -> bytes:
        raise AssertionError("not used")

    async def delete(self, *, object_key: str) -> None:
        raise AssertionError("not used")


class EvidenceEmbeddingProvider:
    async def embed(self, value: str) -> list[float]:
        vector = [0.0] * 1536
        vector[1 if "deadline" in value.lower() else 0] = 1.0
        return vector

    async def embed_many(self, values: list[str]) -> list[list[float]]:
        return [await self.embed(value) for value in values]


async def upload_chunks(content: bytes) -> AsyncIterator[bytes]:
    yield content


async def test_source_evidence_uses_vector_similarity_and_preserves_page() -> None:
    app = create_app()
    container = app.state.container
    user_id = UUID(container.settings.dev_user_id)
    source_id = None
    object_key = None
    try:
        uploaded = await container.sources.upload(
            user_id=user_id,
            filename="semantic-evidence.txt",
            mime_type="text/plain",
            chunks=upload_chunks(b"placeholder"),
            idempotency_key=f"semantic-source-{uuid4()}",
        )
        source_id = uploaded.id
        claimed = await container.sources.claim_next_processing(
            owner="semantic-worker", lease_seconds=60, max_attempts=3
        )
        assert claimed is not None and claimed.id == uploaded.id
        object_key = claimed.object_key
        service = SourceApplicationService(
            container.database.personal_state_unit_of_work,
            UnusedStorage(),
            max_upload_bytes=1024,
            embedding_provider=EvidenceEmbeddingProvider(),
        )
        assert await service.complete_processing(
            source_id=uploaded.id,
            owner="semantic-worker",
            parsed_content=ParsedSourceContent(
                text="general notes\n\ndeadline is Friday",
                pages=(
                    ParsedSourcePage(1, "general notes"),
                    ParsedSourcePage(2, "deadline is Friday"),
                ),
            ),
        )
        assert not await service.complete_processing(
            source_id=uploaded.id,
            owner="semantic-worker",
            parsed_content=ParsedSourceContent(
                text="duplicate retry", pages=(ParsedSourcePage(1, "duplicate retry"),)
            ),
        )

        chunks = await service.get_context_chunks(
            user_id=user_id,
            source_id=uploaded.id,
            query="what is the deadline?",
            max_chunks=2,
        )

        assert chunks[0].content == "deadline is Friday"
        assert chunks[0].page_number == 2
        async with container.database.engine.connect() as connection:
            metadata = await connection.scalar(
                text("SELECT metadata FROM source_chunks WHERE id = :chunk_id"),
                {"chunk_id": chunks[0].id},
            )
            chunk_count = await connection.scalar(
                text("SELECT count(*) FROM source_chunks WHERE source_id = :source_id"),
                {"source_id": uploaded.id},
            )
        assert metadata["parser_version"] == "text-source-v2"
        assert metadata["chunk_version"] == "character-overlap-v1"
        assert chunk_count == 2
    finally:
        if source_id is not None:
            async with container.database.engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM sources WHERE id = :source_id"),
                    {"source_id": source_id},
                )
        if object_key is not None:
            Path(container.settings.object_storage_path, object_key).unlink(missing_ok=True)
        await container.database.dispose()
