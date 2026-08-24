from uuid import uuid4

import pytest

from laoshiren.domain.personal_state.entities import Task
from laoshiren.domain.personal_state.exceptions import InvalidStateTransition
from laoshiren.domain.personal_state.value_objects import TaskStatus


def test_complete_task_records_state_and_version() -> None:
    task = Task(thing_id=uuid4(), title="完成 Demo")

    task.complete()

    assert task.status is TaskStatus.DONE
    assert task.completed_at is not None
    assert task.version == 2


def test_complete_task_is_idempotent_at_domain_level() -> None:
    task = Task(thing_id=uuid4(), title="完成 Demo")
    task.complete()
    completed_at = task.completed_at

    task.complete()

    assert task.completed_at == completed_at
    assert task.version == 2


def test_cancelled_task_cannot_be_completed_directly() -> None:
    task = Task(thing_id=uuid4(), title="完成 Demo", status=TaskStatus.CANCELLED)

    with pytest.raises(InvalidStateTransition):
        task.complete()
