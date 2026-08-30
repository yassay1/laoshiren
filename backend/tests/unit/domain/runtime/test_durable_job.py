from datetime import UTC, datetime
from uuid import uuid4

import pytest

from laoshiren.domain.runtime.entities import DurableJob, DurableJobKind


def test_durable_job_starts_ready_with_stable_dedupe_identity() -> None:
    job = DurableJob(
        user_id=uuid4(),
        kind=DurableJobKind.AGENT_RUN,
        dedupe_key="agent-run:run-1",
        payload={"run_id": "run-1"},
        available_at=datetime.now(UTC),
    )

    assert job.status.value == "READY"
    assert job.claim_epoch == 0
    assert job.delivery_attempt == 0


def test_durable_job_rejects_invalid_delivery_contract() -> None:
    with pytest.raises(ValueError, match="dedupe key"):
        DurableJob(
            user_id=uuid4(),
            kind=DurableJobKind.AGENT_RUN,
            dedupe_key=" ",
            payload={},
        )

    with pytest.raises(ValueError, match="at least one"):
        DurableJob(
            user_id=uuid4(),
            kind=DurableJobKind.AGENT_RUN,
            dedupe_key="agent-run:run-2",
            payload={},
            max_delivery_attempts=0,
        )
