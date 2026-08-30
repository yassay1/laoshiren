import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from laoshiren.domain.identity.value_objects import UserStatus
from laoshiren.main import create_app
from laoshiren.workers.account_deletion import AccountDeletionWorker

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.gate_c,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def test_account_deletion_job_recovers_after_expired_lease() -> None:
    app = create_app()
    subject = f"gate-c-{uuid4()}"
    user_id: UUID | None = None

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            login = await client.post(
                "/api/v1/auth/huawei/login",
                json={"id_token": f"dev:{subject}", "timezone": "UTC"},
            )
            assert login.status_code == 200
            body = login.json()
            user_id = UUID(body["user_id"])
            headers = {"Authorization": f"Bearer {body['access_token']}"}
            delete = await client.delete("/api/v1/me", headers=headers)
            assert delete.status_code == 202

        async with app.state.container.database.engine.begin() as connection:
            job_id = await connection.scalar(
                text(
                    "SELECT id FROM durable_jobs "
                    "WHERE user_id = :user_id AND kind = 'ACCOUNT_DELETION'"
                ),
                {"user_id": user_id},
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

        worker = AccountDeletionWorker(
            app.state.container.database.personal_state_unit_of_work,
            worker_id="recovery-worker",
            lease_seconds=60.0,
        )
        assert await worker.run_once() is True

        async with app.state.container.database.personal_state_unit_of_work() as uow:
            user = await uow.users.get(user_id=user_id)
            assert user is not None
            assert user.status is UserStatus.DELETED
            await uow.rollback()
    finally:
        if user_id is not None:
            async with app.state.container.database.engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM durable_jobs WHERE user_id = :user_id"),
                    {"user_id": user_id},
                )
                await connection.execute(
                    text("DELETE FROM business_sessions WHERE user_id = :user_id"),
                    {"user_id": user_id},
                )
                await connection.execute(
                    text("DELETE FROM users WHERE id = :user_id"),
                    {"user_id": user_id},
                )
        await app.state.container.database.dispose()
