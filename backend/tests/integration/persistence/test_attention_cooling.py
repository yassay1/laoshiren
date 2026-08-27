"""Deterministic integration test for PRD E08 attention cooling."""

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from laoshiren.domain.automations.entities import AttentionFeedbackAction, AttentionSubjectType
from laoshiren.domain.personal_state.value_objects import DateCertainty, DatePrecision
from laoshiren.main import create_app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.database,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1",
        reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests.",
    ),
]


async def test_e08_attention_candidate_suppressed_after_surface() -> None:
    app = create_app()
    container = app.state.container
    user_id = UUID(container.settings.dev_user_id)
    overdue = datetime.now(UTC) - timedelta(hours=2)
    try:
        thing = await container.personal_state.create_thing(
            user_id=user_id,
            name="逾期事项",
            action_id="eval.e08",
            idempotency_key=f"e08-thing-{uuid4()}",
            reason="E08 setup",
        )
        await container.personal_state.set_deadline(
            user_id=user_id,
            thing_id=thing.id,
            kind="DEADLINE",
            value=overdue,
            timezone_name="UTC",
            precision=DatePrecision.DATETIME,
            certainty=DateCertainty.CONFIRMED,
            is_primary=True,
            expected_version=thing.version,
            action_id="eval.e08.deadline",
            idempotency_key=f"e08-deadline-{uuid4()}",
            reason="E08 setup",
        )
        before = await container.attention.get_candidates(user_id=user_id, limit=5)
        assert any(item.thing_id == thing.id for item in before)

        await container.attention.record_feedback(
            user_id=user_id,
            subject_type=AttentionSubjectType.DEADLINE,
            subject_id=thing.id,
            action=AttentionFeedbackAction.SURFACED,
            dismissed_until=None,
        )
        after = await container.attention.get_candidates(user_id=user_id, limit=5)
        assert not any(item.thing_id == thing.id for item in after)
    finally:
        await container.database.dispose()
