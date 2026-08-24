from uuid import UUID, uuid4

import pytest

from laoshiren.infrastructure.runtime.dispatcher import InProcessRunDispatcher

pytestmark = pytest.mark.asyncio


async def test_in_process_dispatcher_consumes_each_run() -> None:
    dispatcher = InProcessRunDispatcher()
    received: list[tuple[UUID, UUID]] = []

    async def execute(*, user_id: UUID, run_id: UUID) -> None:
        received.append((user_id, run_id))

    first = (uuid4(), uuid4())
    second = (uuid4(), uuid4())
    await dispatcher.dispatch(user_id=first[0], run_id=first[1])
    await dispatcher.start(execute)
    await dispatcher.dispatch(user_id=second[0], run_id=second[1])
    await dispatcher.join()
    await dispatcher.stop()

    assert received == [first, second]


async def test_in_process_dispatcher_survives_failed_run() -> None:
    dispatcher = InProcessRunDispatcher()
    received: list[UUID] = []
    failed_run = uuid4()
    successful_run = uuid4()

    async def execute(*, user_id: UUID, run_id: UUID) -> None:
        del user_id
        received.append(run_id)
        if run_id == failed_run:
            raise RuntimeError("persisted by worker")

    await dispatcher.start(execute)
    await dispatcher.dispatch(user_id=uuid4(), run_id=failed_run)
    await dispatcher.dispatch(user_id=uuid4(), run_id=successful_run)
    await dispatcher.join()
    await dispatcher.stop()

    assert received == [failed_run, successful_run]
