from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from laoshiren.domain.automations.entities import AttentionSubjectType
from laoshiren.presentation.api.dependencies import ContainerDependency, CurrentUserId
from laoshiren.presentation.api.schemas.automations import (
    AttentionCandidateResponse,
    AttentionFeedbackRequest,
    AttentionResponse,
)

router = APIRouter(prefix="/attention", tags=["attention"])


@router.get("", response_model=AttentionResponse)
async def get_attention(
    container: ContainerDependency,
    user_id: CurrentUserId,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> AttentionResponse:
    values = await container.attention.get_candidates(user_id=user_id, limit=limit)
    return AttentionResponse(
        items=[AttentionCandidateResponse.from_dto(value) for value in values]
    )


@router.post(
    "/{subject_type}/{subject_id}/feedback", status_code=status.HTTP_204_NO_CONTENT
)
async def record_attention_feedback(
    subject_type: AttentionSubjectType,
    subject_id: UUID,
    request: AttentionFeedbackRequest,
    container: ContainerDependency,
    user_id: CurrentUserId,
) -> None:
    await container.attention.record_feedback(
        user_id=user_id,
        subject_type=subject_type,
        subject_id=subject_id,
        action=request.action,
        dismissed_until=request.dismissed_until,
    )
