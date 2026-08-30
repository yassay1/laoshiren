from uuid import uuid4

from laoshiren.domain.personal_state.entities import Thing
from laoshiren.domain.personal_state.value_objects import ThingStatus


def test_new_thing_is_active_current_reality() -> None:
    assert Thing(user_id=uuid4(), name="软件杯").status is ThingStatus.ACTIVE
