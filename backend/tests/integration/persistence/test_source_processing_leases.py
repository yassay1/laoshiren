import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from laoshiren.domain.sources.entities import ProcessingStatus
from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def chunks(content: bytes) -> AsyncIterator[bytes]:
    yield content


async def test_source_claim_is_exclusive_and_expired_lease_is_recoverable() -> None:
    app = create_app()
    container = app.state.container
    service = container.sources
    user_id = UUID(container.settings.dev_user_id)
    source_id = None
    object_key = None
    try:
        source = await service.upload(
            user_id=user_id,
            filename="worker-test.txt",
            mime_type="text/plain",
            chunks=chunks(b"durable source content"),
            idempotency_key=f"source-worker-{uuid4()}",
        )
        source_id = source.id

        first, second = await asyncio.gather(
            service.claim_next_processing(
                owner="source-worker-a", lease_seconds=60, max_attempts=3
            ),
            service.claim_next_processing(
                owner="source-worker-b", lease_seconds=60, max_attempts=3
            ),
        )
        claimed = first or second
        assert claimed is not None
        assert (first is None) != (second is None)
        first_owner = "source-worker-a" if first is not None else "source-worker-b"
        takeover_owner = "source-worker-b" if first is not None else "source-worker-a"

        async with container.database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE sources SET processing_lease_expires_at = :expired "
                    "WHERE id = :source_id"
                ),
                {
                    "expired": datetime.now(UTC) - timedelta(seconds=1),
                    "source_id": source.id,
                },
            )

        takeover = await service.claim_next_processing(
            owner=takeover_owner, lease_seconds=60, max_attempts=3
        )
        assert takeover is not None
        assert takeover.id == source.id
        assert takeover.attempt_count == 2

        stale_complete = await service.complete_processing(
            source_id=source.id,
            owner=first_owner,
            extracted_text="stale result",
        )
        completed = await service.complete_processing(
            source_id=source.id,
            owner=takeover_owner,
            extracted_text="authoritative result",
        )
        current = await service.get(user_id=user_id, source_id=source.id)

        assert stale_complete is False
        assert completed is True
        assert current.processing_status is ProcessingStatus.READY
        assert current.extracted_text == "authoritative result"
    finally:
        async with container.database.engine.begin() as connection:
            if source_id is not None:
                object_key = await connection.scalar(
                    text("SELECT object_key FROM sources WHERE id = :source_id"),
                    {"source_id": source_id},
                )
                await connection.execute(
                    text("DELETE FROM sources WHERE id = :source_id"),
                    {"source_id": source_id},
                )
        if object_key is not None:
            Path(container.settings.object_storage_path, object_key).unlink(missing_ok=True)
        await container.database.dispose()
