import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def test_source_upload_link_and_query_flow() -> None:
    app = create_app()
    headers = {"Authorization": "Bearer change-me"}
    thing_id: UUID | None = None
    source_id: UUID | None = None
    object_key: str | None = None

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=headers
        ) as client:
            thing_response = await client.post(
                "/api/v1/things",
                headers={"Idempotency-Key": f"source-test-{uuid4()}"},
                json={"name": "来源测试事务"},
            )
            thing_id = UUID(thing_response.json()["id"])

            upload_key = f"source-test-{uuid4()}"
            upload = await client.post(
                "/api/v1/sources",
                headers={"Idempotency-Key": upload_key},
                files={"file": ("notice.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
                data={"origin": "UPLOAD"},
            )
            replay = await client.post(
                "/api/v1/sources",
                headers={"Idempotency-Key": upload_key},
                files={"file": ("ignored.pdf", b"%PDF-1.4\nignored", "application/pdf")},
                data={"origin": "UPLOAD"},
            )

            assert upload.status_code == 201
            assert upload.json()["source_type"] == "PDF"
            assert upload.json()["size"] == 14
            assert upload.json()["replayed"] is False
            assert upload.json()["metadata"]["parser_version"] == "text-source-v2"
            assert upload.json()["metadata"]["chunk_version"] == "character-overlap-v1"
            source_id = UUID(upload.json()["id"])
            assert replay.status_code == 201
            assert replay.json()["id"] == str(source_id)
            assert replay.json()["replayed"] is True

            link_key = f"source-test-{uuid4()}"
            link = await client.post(
                f"/api/v1/things/{thing_id}/sources/{source_id}",
                headers={"Idempotency-Key": link_key},
                json={
                    "relation_type": "PRIMARY",
                    "relevance": 1,
                    "reason": "Source integration test",
                },
            )
            replay_link = await client.post(
                f"/api/v1/things/{thing_id}/sources/{source_id}",
                headers={"Idempotency-Key": link_key},
                json={
                    "relation_type": "PRIMARY",
                    "relevance": 1,
                    "reason": "Source integration replay",
                },
            )
            source = await client.get(f"/api/v1/sources/{source_id}")
            sources = await client.get(f"/api/v1/things/{thing_id}/sources")
            timeline = await client.get(
                f"/api/v1/things/{thing_id}/timeline",
                params={"event_type": "SOURCE_ADDED"},
            )

            assert link.status_code == 200
            assert link.json() == {"created": True}
            assert replay_link.status_code == 200
            assert replay_link.json() == {"created": False}
            assert source.status_code == 200
            assert sources.status_code == 200
            assert [item["id"] for item in sources.json()] == [str(source_id)]
            assert len(timeline.json()) == 1
            assert timeline.json()[0]["source_id"] == str(source_id)

            invalid = await client.post(
                "/api/v1/sources",
                headers={"Idempotency-Key": f"source-test-{uuid4()}"},
                files={"file": ("fake.pdf", b"not-a-pdf", "application/pdf")},
            )
            assert invalid.status_code == 422
            assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
    finally:
        database = app.state.container.database
        async with database.engine.begin() as connection:
            if source_id is not None:
                object_key = await connection.scalar(
                    text("SELECT object_key FROM sources WHERE id = :source_id"),
                    {"source_id": source_id},
                )
            if thing_id is not None:
                for statement in (
                    "DELETE FROM timeline_events WHERE thing_id = :thing_id",
                    "DELETE FROM state_mutations WHERE thing_id = :thing_id",
                    "DELETE FROM thing_sources WHERE thing_id = :thing_id",
                    "DELETE FROM things WHERE id = :thing_id",
                ):
                    await connection.execute(text(statement), {"thing_id": thing_id})
            if source_id is not None:
                await connection.execute(
                    text("DELETE FROM sources WHERE id = :source_id"), {"source_id": source_id}
                )
        if object_key is not None:
            Path(app.state.container.settings.object_storage_path, object_key).unlink(
                missing_ok=True
            )
        await database.dispose()
