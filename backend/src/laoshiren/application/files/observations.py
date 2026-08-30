"""Selective durable promotion for external URL inspections."""

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.domain.files.entities import WebObservation


async def promote_url_inspection(
    uow: PersonalStateUnitOfWork,
    *,
    user_id: UUID,
    requested_url: str,
    payload: dict[str, Any],
    retrieval_method: str = "url_inspect",
) -> UUID:
    items = payload.get("items")
    first: dict[str, Any] = {}
    if isinstance(items, list) and items and isinstance(items[0], dict):
        first = items[0]
    excerpt = str(first.get("snippet", "")).strip()
    bounded_excerpt = excerpt[:8_000] if excerpt else None
    final_url = str(first.get("url", requested_url)).strip() or requested_url
    title = str(first.get("title")).strip() if first.get("title") else None
    content_hash = (
        hashlib.sha256(bounded_excerpt.encode("utf-8")).hexdigest()
        if bounded_excerpt
        else None
    )
    observed_at_raw = payload.get("retrieved_at")
    observed_at = (
        datetime.fromisoformat(str(observed_at_raw))
        if observed_at_raw
        else datetime.now(UTC)
    )
    observation = WebObservation(
        owner_user_id=user_id,
        requested_url=requested_url,
        final_url=final_url,
        title=title,
        content_type="text/html",
        observed_at=observed_at,
        retrieval_method=retrieval_method,
        bounded_excerpt=bounded_excerpt,
        locator={"provider": payload.get("provider")},
        content_hash=content_hash,
    )
    await uow.files.add_web_observation(observation)
    await uow.flush()
    return observation.id
