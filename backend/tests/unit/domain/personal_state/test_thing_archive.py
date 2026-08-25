from uuid import uuid4

from laoshiren.domain.personal_state.entities import Thing


def test_archive_records_timestamp_and_bumps_version() -> None:
    thing = Thing(user_id=uuid4(), name="搬家")

    thing.archive()

    assert thing.archived_at is not None
    assert thing.version == 2


def test_archive_is_idempotent() -> None:
    thing = Thing(user_id=uuid4(), name="搬家")
    thing.archive()
    archived_at = thing.archived_at

    thing.archive()

    assert thing.archived_at == archived_at
    assert thing.version == 2


def test_unarchive_clears_timestamp_and_bumps_version() -> None:
    thing = Thing(user_id=uuid4(), name="搬家")
    thing.archive()

    thing.unarchive()

    assert thing.archived_at is None
    assert thing.version == 3


def test_unarchive_is_idempotent_when_not_archived() -> None:
    thing = Thing(user_id=uuid4(), name="搬家")

    thing.unarchive()

    assert thing.archived_at is None
    assert thing.version == 1
