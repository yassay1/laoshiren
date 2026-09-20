from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from laoshiren.domain.automations.entities import Automation, AutomationStatus, AutomationType


@pytest.mark.parametrize(
    "automation_type",
    [AutomationType.ONE_SHOT, AutomationType.ONCE, AutomationType.RELATIVE],
)
def test_one_shot_clears_due_slot_before_completion(automation_type: AutomationType) -> None:
    due = datetime.now(UTC)
    automation = Automation(
        user_id=uuid4(),
        automation_type=automation_type,
        title="Reminder",
        message="Check result",
        timezone_name="Asia/Shanghai",
        next_trigger_at=due,
        idempotency_key=str(uuid4()),
    )

    automation.mark_triggered(due + timedelta(seconds=1))

    assert automation.next_trigger_at is None
    assert automation.status is AutomationStatus.ACTIVE
    automation.complete_one_shot()
    assert automation.status is AutomationStatus.COMPLETED


def test_new_automation_cannot_start_without_a_trigger() -> None:
    with pytest.raises(ValueError, match="materialized one-shot"):
        Automation(
            user_id=uuid4(),
            automation_type=AutomationType.ONCE,
            title="Reminder",
            message="Check result",
            timezone_name="Asia/Shanghai",
            next_trigger_at=None,
            idempotency_key=str(uuid4()),
        )
