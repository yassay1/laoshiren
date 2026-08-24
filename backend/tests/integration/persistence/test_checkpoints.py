import os

import pytest
from sqlalchemy import text

from laoshiren.config.settings import get_settings
from laoshiren.infrastructure.persistence.checkpoints import PostgresCheckpointLifecycle
from laoshiren.infrastructure.persistence.database import Database

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def test_postgres_checkpoint_lifecycle_sets_up_framework_tables() -> None:
    settings = get_settings()
    lifecycle = PostgresCheckpointLifecycle(settings.database_url)
    database = Database(settings.database_url)
    try:
        first = await lifecycle.start()
        assert lifecycle.saver is first
        assert await lifecycle.start() is first
        async with database.engine.connect() as connection:
            tables = set(
                await connection.scalars(
                    text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname = 'public' AND tablename LIKE 'checkpoint%'"
                    )
                )
            )
        assert {"checkpoints", "checkpoint_writes", "checkpoint_migrations"} <= tables
    finally:
        await lifecycle.stop()
        await lifecycle.stop()
        await database.dispose()
