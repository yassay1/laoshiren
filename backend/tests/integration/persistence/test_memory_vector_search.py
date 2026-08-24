import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from laoshiren.domain.memories.entities import MemoryType
from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def test_pgvector_memory_retrieval_orders_by_cosine_distance() -> None:
    app = create_app()
    user_id = UUID(app.state.container.settings.dev_user_id)
    memory_ids: list[UUID] = []
    positive = [1.0] + [0.0] * 1535
    orthogonal = [0.0, 1.0] + [0.0] * 1534
    try:
        for label, embedding in (("closest", positive), ("other", orthogonal)):
            memory = await app.state.container.memories.create(
                user_id=user_id,
                memory_type=MemoryType.EPISODIC,
                content=f"Vector test {label}",
                summary=label,
                importance=0.5,
                confidence=1,
                idempotency_key=f"memory-vector-{uuid4()}",
                embedding=embedding,
            )
            memory_ids.append(memory.id)

        results = await app.state.container.memories.search(
            user_id=user_id,
            memory_type=MemoryType.EPISODIC,
            query_embedding=positive,
            limit=2,
        )
        matching = [result for result in results if result.id in memory_ids]
        assert [result.id for result in matching] == memory_ids
    finally:
        async with app.state.container.database.engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM long_term_memories WHERE id = ANY(:memory_ids)"),
                {"memory_ids": memory_ids},
            )
        await app.state.container.database.dispose()
