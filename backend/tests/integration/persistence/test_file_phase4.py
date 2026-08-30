import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from laoshiren.application.sources.ports import ParsedSourceContent
from laoshiren.application.sources.service import SourceApplicationService
from laoshiren.infrastructure.storage.local import LocalObjectStorage
from laoshiren.main import create_app
from laoshiren.workers.file_purge import FilePurgeWorker

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def upload_chunks(content: bytes) -> AsyncIterator[bytes]:
    yield content


async def test_file_backfill_matches_source_identity() -> None:
    app = create_app()
    container = app.state.container
    user_id = uuid4()
    source_id = None
    object_key = None
    try:
        uploaded = await container.sources.upload(
            user_id=user_id,
            filename="backfill.txt",
            mime_type="text/plain",
            chunks=upload_chunks(b"backfill content"),
            idempotency_key=f"backfill-{uuid4()}",
        )
        source_id = uploaded.id
        async with container.database.engine.connect() as connection:
            file_count = await connection.scalar(
                text("SELECT count(*) FROM files WHERE id = :file_id"),
                {"file_id": uploaded.id},
            )
            generation_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM file_processing_generations "
                    "WHERE file_id = :file_id AND is_active = TRUE"
                ),
                {"file_id": uploaded.id},
            )
        assert file_count == 1
        assert generation_count == 0
        claimed = await container.sources.claim_next_processing(
            owner="backfill-worker",
            user_id=user_id,
            lease_seconds=60,
            max_attempts=3,
        )
        assert claimed is not None
        object_key = claimed.object_key
        service = SourceApplicationService(
            container.database.personal_state_unit_of_work,
            LocalObjectStorage(Path(container.settings.object_storage_path)),
            max_upload_bytes=1024,
        )
        assert await service.complete_processing(
            source_id=uploaded.id,
            owner="backfill-worker",
            parsed_content=ParsedSourceContent(text="backfill content", pages=()),
        )
        async with container.database.engine.connect() as connection:
            segment_count = await connection.scalar(
                text("SELECT count(*) FROM retrieval_segments WHERE file_id = :file_id"),
                {"file_id": uploaded.id},
            )
            chunk_count = await connection.scalar(
                text("SELECT count(*) FROM source_chunks WHERE source_id = :source_id"),
                {"source_id": uploaded.id},
            )
        assert segment_count == chunk_count
        assert segment_count >= 1
    finally:
        if source_id is not None:
            async with container.database.engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM files WHERE id = :source_id"),
                    {"source_id": source_id},
                )
                await connection.execute(
                    text("DELETE FROM sources WHERE id = :source_id"),
                    {"source_id": source_id},
                )
        if object_key is not None:
            Path(container.settings.object_storage_path, object_key).unlink(missing_ok=True)
        await container.database.dispose()


async def test_file_delete_enqueues_physical_purge() -> None:
    app = create_app()
    container = app.state.container
    user_id = uuid4()
    source_id = None
    object_key = None
    try:
        uploaded = await container.sources.upload(
            user_id=user_id,
            filename="purge-me.txt",
            mime_type="text/plain",
            chunks=upload_chunks(b"purge"),
            idempotency_key=f"purge-{uuid4()}",
        )
        source_id = uploaded.id
        async with container.database.engine.connect() as connection:
            row = await connection.execute(
                text("SELECT object_key FROM sources WHERE id = :id"),
                {"id": source_id},
            )
            object_key = str(row.scalar_one())
        await container.sources.delete_file(
            user_id=user_id,
            source_id=source_id,
            action_id="delete-1",
            idempotency_key=f"delete-{uuid4()}",
            reason="test purge",
        )
        async with container.database.engine.connect() as connection:
            job_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM durable_jobs "
                    "WHERE kind = 'FILE_PURGE' AND payload->>'file_id' = :file_id"
                ),
                {"file_id": str(source_id)},
            )
            purged_at = await connection.scalar(
                text("SELECT purged_at FROM files WHERE id = :file_id"),
                {"file_id": source_id},
            )
        assert job_count == 1
        assert purged_at is None
        assert Path(container.settings.object_storage_path, object_key).exists()
        worker = FilePurgeWorker(
            container.database.personal_state_unit_of_work,
            LocalObjectStorage(Path(container.settings.object_storage_path)),
        )
        assert await worker.run_once()
        assert not Path(container.settings.object_storage_path, object_key).exists()
        async with container.database.engine.connect() as connection:
            purged_at = await connection.scalar(
                text("SELECT purged_at FROM files WHERE id = :file_id"),
                {"file_id": source_id},
            )
        assert purged_at is not None
    finally:
        if source_id is not None:
            async with container.database.engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM durable_jobs WHERE payload->>'file_id' = :file_id"),
                    {"file_id": str(source_id)},
                )
                await connection.execute(
                    text("DELETE FROM files WHERE id = :source_id"),
                    {"source_id": source_id},
                )
                await connection.execute(
                    text("DELETE FROM sources WHERE id = :source_id"),
                    {"source_id": source_id},
                )
        await container.database.dispose()
