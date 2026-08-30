from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from laoshiren.presentation.api.dependencies import (
    ContainerDependency,
    CurrentUserId,
    IdempotencyKey,
)
from laoshiren.presentation.api.schemas.automations import (
    AutomationResponse,
    ChangeAutomationRequest,
    CreateAutomationRequest,
    NotificationResponse,
)

router = APIRouter(prefix="/automations", tags=["automations"])


@router.get("", response_model=list[AutomationResponse])
async def list_automations(
    container: ContainerDependency,
    user_id: CurrentUserId,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[AutomationResponse]:
    values = await container.automations.list_automations(user_id=user_id, limit=limit)
    return [AutomationResponse.from_dto(value) for value in values]


@router.post("", response_model=AutomationResponse, status_code=status.HTTP_201_CREATED)
async def create_automation(
    request: CreateAutomationRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> AutomationResponse:
    value = await container.automations.create(
        user_id=user_id,
        automation_type=request.automation_type,
        title=request.title,
        message=request.message,
        timezone_name=request.timezone,
        next_trigger_at=request.next_trigger_at,
        idempotency_key=idempotency_key,
        thing_id=request.thing_id,
        task_id=request.task_id,
        source_id=request.source_id,
        recurrence_interval_seconds=request.recurrence_interval_seconds,
    )
    return AutomationResponse.from_dto(value)


@router.get("/notifications", response_model=list[NotificationResponse])
async def list_notifications(
    container: ContainerDependency,
    user_id: CurrentUserId,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[NotificationResponse]:
    values = await container.automations.list_notifications(user_id=user_id, limit=limit)
    return [NotificationResponse.from_dto(value) for value in values]


@router.get("/{automation_id}", response_model=AutomationResponse)
async def get_automation(
    automation_id: UUID,
    container: ContainerDependency,
    user_id: CurrentUserId,
) -> AutomationResponse:
    value = await container.automations.get(user_id=user_id, automation_id=automation_id)
    return AutomationResponse.from_dto(value)


@router.patch("/{automation_id}", response_model=AutomationResponse)
async def change_automation(
    automation_id: UUID,
    request: ChangeAutomationRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> AutomationResponse:
    value = await container.automations.change_status(
        user_id=user_id,
        automation_id=automation_id,
        action=request.action,
        expected_version=request.expected_version,
        idempotency_key=idempotency_key,
    )
    return AutomationResponse.from_dto(value)


@router.delete("/{automation_id}", response_model=AutomationResponse)
async def cancel_automation(
    automation_id: UUID,
    expected_version: Annotated[int, Query(ge=1)],
    container: ContainerDependency,
    user_id: CurrentUserId,
    idempotency_key: IdempotencyKey,
) -> AutomationResponse:
    value = await container.automations.change_status(
        user_id=user_id,
        automation_id=automation_id,
        action="CANCEL",
        expected_version=expected_version,
        idempotency_key=idempotency_key,
    )
    return AutomationResponse.from_dto(value)
