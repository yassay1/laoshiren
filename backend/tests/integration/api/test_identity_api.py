import os
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from laoshiren.domain.identity.value_objects import UserStatus
from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def test_identity_login_device_and_account_deletion_flow() -> None:
    app = create_app()
    device_id = uuid4()
    subject = f"phase7-{uuid4()}"

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            login = await client.post(
                "/api/v1/auth/huawei/login",
                json={
                    "id_token": f"dev:{subject}",
                    "device_id": str(device_id),
                    "timezone": "Asia/Shanghai",
                },
            )
            assert login.status_code == 200
            body = login.json()
            access_token = body["access_token"]
            user_id = UUID(body["user_id"])
            headers = {"Authorization": f"Bearer {access_token}"}

            refresh = await client.post("/api/v1/auth/refresh", headers=headers)
            assert refresh.status_code == 200
            refreshed = refresh.json()
            new_token = refreshed["access_token"]
            assert refreshed["user_id"] == str(user_id)
            assert new_token != access_token

            old_headers = headers
            headers = {"Authorization": f"Bearer {new_token}"}
            profile = await client.get("/api/v1/me", headers=headers)
            assert profile.status_code == 200

            stale = await client.get("/api/v1/me", headers=old_headers)
            assert stale.status_code == 401

            profile = await client.get("/api/v1/me", headers=headers)
            assert profile.status_code == 200
            assert profile.json()["status"] == UserStatus.ACTIVE.value

            register = await client.post(
                "/api/v1/devices/register",
                headers=headers,
                json={
                    "device_id": str(device_id),
                    "timezone": "Asia/Shanghai",
                },
            )
            assert register.status_code == 200

            push = await client.put(
                f"/api/v1/devices/{device_id}/push-token",
                headers=headers,
                json={"push_token": "test-push-token"},
            )
            assert push.status_code == 204

            delete = await client.delete("/api/v1/me", headers=headers)
            assert delete.status_code == 202

            for _ in range(10):
                processed = await app.state.container.account_deletion_scheduler.run_batch()
                if processed:
                    break

            profile_after = await client.get("/api/v1/me", headers=headers)
            assert profile_after.status_code == 401

            async with app.state.container.database.personal_state_unit_of_work() as uow:
                user = await uow.users.get(user_id=user_id)
                assert user is not None
                assert user.status is UserStatus.DELETED
                await uow.rollback()
    finally:
        await app.state.container.database.dispose()
