import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from laoshiren.infrastructure.storage.local import LocalObjectStorage
from laoshiren.main import create_app
from laoshiren.workers.file_purge import FilePurgeWorker

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.gate_c,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def upload_chunks(content: bytes) -> AsyncIterator[bytes]:
    yield content


async def test_file_purge_job_recovers_after_expired_lease() -> None:
    app = create_app()
    container = app.state.container
    user_id = uuid4()
    source_id = None
    object_key = None

    try:
        uploaded = await container.sources.upload(
            user_id=user_id,
            filename="gate-c-purge.txt",
            mime_type="text/plain",
            chunks=upload_chunks(b"purge after requeue"),
            idempotency_key=f"gate-c-purge-{uuid4()}",
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
            action_id="gate-c-delete",
            idempotency_key=f"gate-c-delete-{uuid4()}",
            reason="gate c purge recovery",
        )

        async with container.database.engine.begin() as connection:
            job_id = await connection.scalar(
                text(
                    "SELECT id FROM durable_jobs "
                    "WHERE kind = 'FILE_PURGE' AND payload->>'file_id' = :file_id"
                ),
                {"file_id": str(source_id)},
            )
            assert job_id is not None
            await connection.execute(
                text(
                    "UPDATE durable_jobs "
                    "SET status = 'CLAIMED', claimed_by = 'stale-worker', "
                    "lease_until = :expired, claim_epoch = 1 "
                    "WHERE id = :job_id"
                ),
                {
                    "expired": datetime.now(UTC) - timedelta(seconds=30),
                    "job_id": job_id,
                },
            )

        worker = FilePurgeWorker(
            container.database.personal_state_unit_of_work,
            LocalObjectStorage(Path(container.settings.object_storage_path)),
            worker_id="recovery-file-purge",
        )
        assert await worker.run_once() is True
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
        if object_key is not None:
            Path(container.settings.object_storage_path, object_key).unlink(missing_ok=True)
        await container.database.dispose()
