from datetime import UTC, datetime
from uuid import uuid4

from laoshiren.application.context import AgentContextBuilder
from laoshiren.application.personal_state.dto import (
    ActiveThingDTO,
    BlockedThingDTO,
    RecentThingDTO,
    StateOverviewDTO,
    UpcomingThingDTO,
)
from laoshiren.application.runtime.dto import MessageDTO
from laoshiren.domain.personal_state.value_objects import BlockerSeverity, ThingStatus
from laoshiren.domain.runtime.entities import MessageRole


def message(index: int, *, size: int = 20) -> MessageDTO:
    return MessageDTO(
        id=uuid4(),
        thread_id=uuid4(),
        role=MessageRole.USER if index % 2 == 0 else MessageRole.ASSISTANT,
        content=f"message-{index}-" + ("x" * size),
        run_id=uuid4(),
        source_ids=[],
        metadata={},
        created_at=datetime.now(UTC),
    )


def test_short_thread_is_not_summarized() -> None:
    messages = [message(index) for index in range(4)]

    context = AgentContextBuilder().build(messages=messages)

    assert [item["id"] for item in context.messages] == [
        str(item.id) for item in messages
    ]
    assert "thread_summary" not in context.prefetched_state
    assert context.prefetched_state["context_stats"]["summarized_message_count"] == 0


def test_long_thread_keeps_recent_messages_and_summarizes_older_messages() -> None:
    messages = [message(index, size=40) for index in range(12)]
    builder = AgentContextBuilder(
        total_characters=1_200,
        recent_message_characters=300,
        summary_characters=400,
        memory_characters=200,
        source_characters=200,
        recent_message_count=4,
    )

    context = builder.build(messages=messages)

    assert [item["id"] for item in context.messages] == [
        str(item.id) for item in messages[-4:]
    ]
    assert "message-0" in context.prefetched_state["thread_summary"]
    assert "message-7" in context.prefetched_state["thread_summary"]
    assert context.prefetched_state["context_stats"]["summarized_message_count"] == 8


def test_profile_memory_precedes_relevant_memory_and_sources_are_bounded() -> None:
    builder = AgentContextBuilder(
        total_characters=500,
        recent_message_characters=100,
        summary_characters=100,
        memory_characters=100,
        source_characters=80,
        recent_message_count=2,
    )
    memory_context = {
        "profile": [{"content": "profile", "summary": "style"}],
        "relevant": [{"content": "r" * 200, "summary": "large"}],
    }
    sources = [{"source_id": "one", "content": "s" * 200}]

    context = builder.build(
        messages=[message(1, size=10)],
        memory_context=memory_context,
        source_context=sources,
    )

    assert context.prefetched_state["memory_context"]["profile"] == [
        {"content": "profile", "summary": "style"}
    ]
    assert context.prefetched_state["memory_context"]["relevant"] == []
    assert len(context.prefetched_state["source_context"][0]["content"]) == 80


def test_state_overview_is_injected_into_prefetched_state() -> None:
    overview = StateOverviewDTO(
        upcoming=(UpcomingThingDTO(uuid4(), "搬家", datetime.now(UTC), 2),),
        blocked=(BlockedThingDTO(uuid4(), "搬家", "等报价", BlockerSeverity.HIGH),),
        active=(ActiveThingDTO(uuid4(), "学车", "练习中", 1),),
        recent=(RecentThingDTO(uuid4(), "搬家", ThingStatus.ACTIVE, datetime.now(UTC)),),
    )

    context = AgentContextBuilder().build(
        messages=[message(1, size=10)], state_overview=overview
    )

    data = context.prefetched_state["state_overview"]
    assert data["upcoming"][0]["name"] == "搬家"
    assert data["upcoming"][0]["open_tasks"] == 2
    assert data["blocked"][0]["severity"] == "HIGH"
    assert data["active"][0]["stage"] == "练习中"
    assert data["recent"][0]["status"] == "ACTIVE"


def test_state_overview_is_trimmed_to_budget() -> None:
    overview = StateOverviewDTO(
        upcoming=tuple(
            UpcomingThingDTO(uuid4(), f"事务-{index}", datetime.now(UTC), 1)
            for index in range(30)
        ),
        blocked=(),
        active=(),
        recent=(),
    )
    builder = AgentContextBuilder(state_overview_characters=200)

    context = builder.build(messages=[message(1, size=10)], state_overview=overview)

    data = context.prefetched_state["state_overview"]
    assert len(data["upcoming"]) < 30
