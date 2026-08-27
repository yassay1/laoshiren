from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from laoshiren.application.personal_state.dto import StateOverviewDTO
from laoshiren.domain.personal_state.value_objects import BlockerSeverity, ThingStatus


class UpcomingThingResponse(BaseModel):
    thing_id: UUID
    name: str
    deadline_at: datetime
    open_task_count: int


class BlockedThingResponse(BaseModel):
    thing_id: UUID
    thing_name: str
    description: str
    severity: BlockerSeverity


class ActiveThingResponse(BaseModel):
    thing_id: UUID
    name: str
    current_stage: str | None
    open_task_count: int


class RecentThingResponse(BaseModel):
    thing_id: UUID
    name: str
    status: ThingStatus
    updated_at: datetime


class StateOverviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    upcoming: list[UpcomingThingResponse]
    blocked: list[BlockedThingResponse]
    active: list[ActiveThingResponse]
    recent: list[RecentThingResponse]

    @classmethod
    def from_dto(cls, value: StateOverviewDTO) -> "StateOverviewResponse":
        return cls(
            upcoming=[
                UpcomingThingResponse(
                    thing_id=item.thing_id,
                    name=item.name,
                    deadline_at=item.deadline_at,
                    open_task_count=item.open_task_count,
                )
                for item in value.upcoming
            ],
            blocked=[
                BlockedThingResponse(
                    thing_id=item.thing_id,
                    thing_name=item.thing_name,
                    description=item.description,
                    severity=item.severity,
                )
                for item in value.blocked
            ],
            active=[
                ActiveThingResponse(
                    thing_id=item.thing_id,
                    name=item.name,
                    current_stage=item.current_stage,
                    open_task_count=item.open_task_count,
                )
                for item in value.active
            ],
            recent=[
                RecentThingResponse(
                    thing_id=item.thing_id,
                    name=item.name,
                    status=item.status,
                    updated_at=item.updated_at,
                )
                for item in value.recent
            ],
        )
