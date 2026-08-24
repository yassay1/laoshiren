import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from laoshiren.application.personal_state.service import PersonalStateApplicationService
from laoshiren.domain.personal_state.exceptions import VersionConflict
from laoshiren.domain.personal_state.value_objects import DateCertainty, DatePrecision
from laoshiren.infrastructure.persistence.database import Database

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def test_complete_task_is_atomic_idempotent_and_versioned() -> None:
    database = Database("postgresql+asyncpg://laoshiren:laoshiren@localhost:5432/laoshiren")
    service = PersonalStateApplicationService(database.personal_state_unit_of_work)
    user_id = uuid4()

    try:
        thing = await service.create_thing(
            user_id=user_id,
            name="集成测试事务",
            action_id="create-thing",
            idempotency_key=f"test:{uuid4()}",
            reason="integration test",
        )
        deadline_value = datetime.now(UTC) + timedelta(days=7)
        deadline_key = f"test:{uuid4()}"
        deadline = await service.set_deadline(
            user_id=user_id,
            thing_id=thing.id,
            kind="SUBMISSION_DEADLINE",
            value=deadline_value,
            timezone_name="Asia/Shanghai",
            precision=DatePrecision.DATETIME,
            certainty=DateCertainty.CONFIRMED,
            is_primary=True,
            expected_version=thing.version,
            action_id="set-deadline",
            idempotency_key=deadline_key,
            reason="integration test",
        )
        deadline_replay = await service.set_deadline(
            user_id=user_id,
            thing_id=thing.id,
            kind="SUBMISSION_DEADLINE",
            value=deadline_value,
            timezone_name="Asia/Shanghai",
            precision=DatePrecision.DATETIME,
            certainty=DateCertainty.CONFIRMED,
            is_primary=True,
            expected_version=thing.version,
            action_id="set-deadline",
            idempotency_key=deadline_key,
            reason="integration test replay",
        )
        assert deadline.target_version == 2
        assert deadline_replay.replayed is True
        assert deadline_replay.mutation_id == deadline.mutation_id

        refreshed_thing = await service.get_thing(user_id=user_id, thing_id=thing.id)
        assert refreshed_thing.deadline_at == deadline_value
        assert refreshed_thing.version == 2

        task = await service.create_task(
            user_id=user_id,
            thing_id=thing.id,
            title="完成集成测试",
            action_id="create-task",
            idempotency_key=f"test:{uuid4()}",
            reason="integration test",
        )
        idempotency_key = f"test:{uuid4()}"

        first = await service.complete_task(
            user_id=user_id,
            task_id=task.id,
            expected_version=task.version,
            action_id="complete-task",
            idempotency_key=idempotency_key,
            reason="integration test",
        )
        replay = await service.complete_task(
            user_id=user_id,
            task_id=task.id,
            expected_version=task.version,
            action_id="complete-task",
            idempotency_key=idempotency_key,
            reason="integration test replay",
        )

        assert first.replayed is False
        assert replay.replayed is True
        assert replay.mutation_id == first.mutation_id
        assert first.target_version == 2

        with pytest.raises(VersionConflict):
            await service.complete_task(
                user_id=user_id,
                task_id=task.id,
                expected_version=1,
                action_id="stale-complete-task",
                idempotency_key=f"test:{uuid4()}",
                reason="stale integration test",
            )

        async with database.engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT t.status::text, t.version,
                               COUNT(DISTINCT sm.id), COUNT(DISTINCT te.id)
                        FROM tasks t
                        LEFT JOIN state_mutations sm
                          ON sm.target_id = t.id AND sm.mutation_type = 'TASK_COMPLETED'
                        LEFT JOIN timeline_events te ON te.mutation_id = sm.id
                        WHERE t.id = :task_id
                        GROUP BY t.status, t.version
                        """
                    ),
                    {"task_id": task.id},
                )
            ).one()

        assert row == ("DONE", 2, 1, 1)
    finally:
        async with database.engine.begin() as connection:
            statements = [
                "DELETE FROM timeline_events WHERE user_id = :user_id",
                "DELETE FROM state_mutations WHERE user_id = :user_id",
                """DELETE FROM tasks WHERE thing_id IN (
                    SELECT id FROM things WHERE user_id = :user_id
                )""",
                """DELETE FROM thing_dates WHERE thing_id IN (
                    SELECT id FROM things WHERE user_id = :user_id
                )""",
                "DELETE FROM things WHERE user_id = :user_id",
                "DELETE FROM users WHERE id = :user_id",
            ]
            for statement in statements:
                await connection.execute(text(statement), {"user_id": user_id})
        await database.dispose()
