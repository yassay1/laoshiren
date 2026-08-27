from datetime import datetime

from pydantic import BaseModel, ConfigDict

from laoshiren.application.automations.dto import AttentionCandidateDTO
from laoshiren.application.personal_state.dto import StateOverviewDTO
from laoshiren.presentation.api.schemas.automations import AttentionCandidateResponse
from laoshiren.presentation.api.schemas.state import (
    ActiveThingResponse,
    BlockedThingResponse,
    RecentThingResponse,
    UpcomingThingResponse,
)


class TodayResponse(BaseModel):
    """Aggregated read model for the Today product surface."""

    model_config = ConfigDict(from_attributes=True)

    attention: list[AttentionCandidateResponse]
    upcoming: list[UpcomingThingResponse]
    overdue: list[UpcomingThingResponse]
    due_today: list[UpcomingThingResponse]
    blocked: list[BlockedThingResponse]
    active: list[ActiveThingResponse]
    recent: list[RecentThingResponse]
    generated_at: datetime

    @classmethod
    def from_sources(
        cls,
        *,
        attention: list[AttentionCandidateDTO],
        overview: StateOverviewDTO,
        now: datetime,
    ) -> "TodayResponse":
        today = now.date()
        upcoming = list(overview.upcoming)
        overdue = [
            item for item in upcoming if item.deadline_at.date() < today
        ]
        due_today = [
            item for item in upcoming if item.deadline_at.date() == today
        ]
        return cls(
            attention=[AttentionCandidateResponse.from_dto(item) for item in attention],
            upcoming=[
                UpcomingThingResponse(
                    thing_id=item.thing_id,
                    name=item.name,
                    deadline_at=item.deadline_at,
                    open_task_count=item.open_task_count,
                )
                for item in upcoming
            ],
            overdue=[
                UpcomingThingResponse(
                    thing_id=item.thing_id,
                    name=item.name,
                    deadline_at=item.deadline_at,
                    open_task_count=item.open_task_count,
                )
                for item in overdue
            ],
            due_today=[
                UpcomingThingResponse(
                    thing_id=item.thing_id,
                    name=item.name,
                    deadline_at=item.deadline_at,
                    open_task_count=item.open_task_count,
                )
                for item in due_today
            ],
            blocked=[
                BlockedThingResponse(
                    thing_id=item.thing_id,
                    thing_name=item.thing_name,
                    description=item.description,
                    severity=item.severity,
                )
                for item in overview.blocked
            ],
            active=[
                ActiveThingResponse(
                    thing_id=item.thing_id,
                    name=item.name,
                    current_stage=item.current_stage,
                    open_task_count=item.open_task_count,
                )
                for item in overview.active
            ],
            recent=[
                RecentThingResponse(
                    thing_id=item.thing_id,
                    name=item.name,
                    status=item.status,
                    updated_at=item.updated_at,
                )
                for item in overview.recent
            ],
            generated_at=now,
        )
