import os

import pytest
from httpx import ASGITransport, AsyncClient

from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def test_readiness_reports_persistent_worker_backlogs() -> None:
    app = create_app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/health/ready")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert set(body["backlogs"]) == {
            "runs_queued",
            "runs_expired",
            "sources_due",
            "automations_due",
            "notifications_due",
            "durable_jobs_ready",
        }
        assert all(value >= 0 for value in body["backlogs"].values())
    finally:
        await app.state.container.database.dispose()


async def test_metrics_endpoint_exports_prometheus_backlog_gauges() -> None:
    app = create_app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/health/metrics")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        body = response.text
        assert "laoshiren_backlog{name=\"runs_queued\"}" in body
        assert "laoshiren_backlog{name=\"durable_jobs_ready\"}" in body
    finally:
        await app.state.container.database.dispose()
