from uuid import uuid4

import pytest

from laoshiren.domain.personal_state.entities import ThingContextEntry


def test_context_entry_revise_replaces_current_value_and_bumps_version() -> None:
    entry = ThingContextEntry(thing_id=uuid4(), label="导师关注", content="先完成 Demo")

    entry.revise(label="导师关注", content="先完成可运行的 Demo")

    assert entry.content == "先完成可运行的 Demo"
    assert entry.version == 2


def test_context_entry_rejects_blank_current_value() -> None:
    entry = ThingContextEntry(thing_id=uuid4(), label="导师关注", content="先完成 Demo")

    with pytest.raises(ValueError):
        entry.revise(label="", content="x")
