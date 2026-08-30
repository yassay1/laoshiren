import asyncio
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from laoshiren.application.memories.context import AgentMemoryApplicationService
from laoshiren.domain.memories.entities import MemoryStatus, MemoryType
from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def test_concurrent_profile_updates_leave_one_active_version_for_context() -> None:
    app = create_app()
    container = app.state.container
    user_id = UUID(container.settings.dev_user_id)
    memory_ids: list[UUID] = []
    try:
        first, second = await asyncio.gather(
            container.memories.create(
                user_id=user_id,
                memory_type=MemoryType.PROFILE,
                content="回答要简洁",
                summary="简洁回答",
                importance=0.8,
                confidence=1,
                idempotency_key=f"profile-{uuid4()}",
                profile_key="preference:response_style",
            ),
            container.memories.create(
                user_id=user_id,
                memory_type=MemoryType.PROFILE,
                content="回答要详细并给示例",
                summary="详细回答",
                importance=0.8,
                confidence=1,
                idempotency_key=f"profile-{uuid4()}",
                profile_key="preference:response_style",
            ),
        )
        memory_ids = [first.id, second.id]
        stored = await container.memories.search(
            user_id=user_id, memory_type=MemoryType.PROFILE, limit=10
        )
        matching = [item for item in stored if item.id in memory_ids]
        context = await AgentMemoryApplicationService(container.memories).load_context(
            user_id=user_id, query="我偏好怎样的回答"
        )
        context_matching = [item for item in context.profile if item.id in memory_ids]

        assert len(matching) == 1
        assert matching[0].status is MemoryStatus.ACTIVE
        assert matching[0].profile_key == "preference:response_style"
        assert matching[0].supersedes_id in memory_ids
        assert matching[0].supersedes_id != matching[0].id
        assert [item.id for item in context_matching] == [matching[0].id]

        async with container.database.engine.connect() as connection:
            statuses = (
                (
                    await connection.execute(
                        text(
                            "SELECT status FROM long_term_memories "
                            "WHERE id = ANY(:memory_ids) ORDER BY status"
                        ),
                        {"memory_ids": memory_ids},
                    )
                )
                .scalars()
                .all()
            )
        assert set(statuses) == {"ACTIVE", "SUPERSEDED"}
    finally:
        if memory_ids:
            async with container.database.engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM long_term_memories WHERE id = ANY(:memory_ids)"),
                    {"memory_ids": memory_ids},
                )
        await container.database.dispose()
