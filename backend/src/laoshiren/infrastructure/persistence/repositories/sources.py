from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from laoshiren.domain.sources.entities import Source, ThingSource
from laoshiren.infrastructure.persistence.orm.personal_state import (
    SourceORM,
    ThingORM,
    ThingSourceORM,
)


def source_to_domain(model: SourceORM) -> Source:
    return Source(
        id=model.id,
        user_id=model.user_id,
        source_type=model.source_type,
        origin=model.origin,
        title=model.title,
        mime_type=model.mime_type,
        object_key=model.object_key,
        external_url=model.external_url,
        content_hash=model.content_hash,
        size=model.size,
        captured_at=model.captured_at,
        metadata=model.metadata_,
        processing_status=model.processing_status,
        extracted_text=model.extracted_text,
        processing_error=model.processing_error,
        processed_at=model.processed_at,
        processing_claim_owner=model.processing_claim_owner,
        processing_lease_expires_at=model.processing_lease_expires_at,
        processing_heartbeat_at=model.processing_heartbeat_at,
        processing_attempt_count=model.processing_attempt_count,
        next_processing_attempt_at=model.next_processing_attempt_at,
        idempotency_key=model.idempotency_key,
        created_at=model.created_at,
    )


class SqlAlchemySourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, source: Source) -> None:
        self._session.add(
            SourceORM(
                id=source.id,
                user_id=source.user_id,
                source_type=source.source_type,
                origin=source.origin,
                title=source.title,
                mime_type=source.mime_type,
                object_key=source.object_key,
                external_url=source.external_url,
                content_hash=source.content_hash,
                size=source.size,
                captured_at=source.captured_at,
                metadata_=source.metadata,
                processing_status=source.processing_status,
                extracted_text=source.extracted_text,
                processing_error=source.processing_error,
                processed_at=source.processed_at,
                processing_claim_owner=source.processing_claim_owner,
                processing_lease_expires_at=source.processing_lease_expires_at,
                processing_heartbeat_at=source.processing_heartbeat_at,
                processing_attempt_count=source.processing_attempt_count,
                next_processing_attempt_at=source.next_processing_attempt_at,
                idempotency_key=source.idempotency_key,
                created_at=source.created_at,
            )
        )

    async def get(self, *, user_id: UUID, source_id: UUID) -> Source | None:
        model = await self._session.scalar(
            select(SourceORM).where(SourceORM.id == source_id, SourceORM.user_id == user_id)
        )
        return source_to_domain(model) if model is not None else None

    async def get_by_idempotency(self, *, user_id: UUID, key: str) -> Source | None:
        model = await self._session.scalar(
            select(SourceORM).where(
                SourceORM.user_id == user_id, SourceORM.idempotency_key == key
            )
        )
        return source_to_domain(model) if model is not None else None

    async def add_relation(self, relation: ThingSource) -> bool:
        statement = (
            insert(ThingSourceORM)
            .values(
                thing_id=relation.thing_id,
                source_id=relation.source_id,
                relation_type=relation.relation_type,
                relevance=relation.relevance,
                created_at=relation.created_at,
            )
            .on_conflict_do_nothing(index_elements=["thing_id", "source_id"])
            .returning(ThingSourceORM.source_id)
        )
        return (await self._session.scalar(statement)) is not None

    async def list_for_thing(self, *, user_id: UUID, thing_id: UUID) -> list[Source]:
        statement = (
            select(SourceORM)
            .join(ThingSourceORM, ThingSourceORM.source_id == SourceORM.id)
            .join(ThingORM, ThingORM.id == ThingSourceORM.thing_id)
            .where(ThingSourceORM.thing_id == thing_id, ThingORM.user_id == user_id)
            .order_by(SourceORM.created_at.desc(), SourceORM.id.desc())
        )
        models = (await self._session.scalars(statement)).all()
        return [source_to_domain(model) for model in models]

    async def claim_next_processing(
        self,
        *,
        owner: str,
        now: datetime,
        lease_expires_at: datetime,
        supported_mime_types: tuple[str, ...],
        max_attempts: int,
    ) -> Source | None:
        candidate = (
            select(SourceORM.id)
            .where(
                SourceORM.mime_type.in_(supported_mime_types),
                SourceORM.processing_attempt_count < max_attempts,
                or_(
                    and_(
                        SourceORM.processing_status == "PENDING",
                        or_(
                            SourceORM.processing_lease_expires_at.is_(None),
                            SourceORM.processing_lease_expires_at <= now,
                        ),
                    ),
                    and_(
                        SourceORM.processing_status == "FAILED",
                        SourceORM.next_processing_attempt_at.is_not(None),
                        SourceORM.next_processing_attempt_at <= now,
                    ),
                ),
            )
            .order_by(SourceORM.created_at, SourceORM.id)
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        model = await self._session.scalar(
            update(SourceORM)
            .where(SourceORM.id == candidate)
            .values(
                processing_status="PENDING",
                processing_claim_owner=owner,
                processing_lease_expires_at=lease_expires_at,
                processing_heartbeat_at=now,
                processing_attempt_count=SourceORM.processing_attempt_count + 1,
                next_processing_attempt_at=None,
                processed_at=None,
            )
            .returning(SourceORM)
        )
        return source_to_domain(model) if model is not None else None

    async def renew_processing_lease(
        self,
        *,
        source_id: UUID,
        owner: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(SourceORM)
                .where(
                    SourceORM.id == source_id,
                    SourceORM.processing_status == "PENDING",
                    SourceORM.processing_claim_owner == owner,
                )
                .values(
                    processing_heartbeat_at=now,
                    processing_lease_expires_at=lease_expires_at,
                )
            ),
        )
        return result.rowcount == 1

    async def complete_processing(
        self,
        *,
        source_id: UUID,
        owner: str,
        extracted_text: str,
        now: datetime,
    ) -> bool:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(SourceORM)
                .where(
                    SourceORM.id == source_id,
                    SourceORM.processing_status == "PENDING",
                    SourceORM.processing_claim_owner == owner,
                )
                .values(
                    processing_status="READY",
                    extracted_text=extracted_text,
                    processing_error=None,
                    processed_at=now,
                    processing_claim_owner=None,
                    processing_lease_expires_at=None,
                    processing_heartbeat_at=None,
                    next_processing_attempt_at=None,
                )
            ),
        )
        return result.rowcount == 1

    async def fail_processing(
        self,
        *,
        source_id: UUID,
        owner: str,
        error_code: str,
        now: datetime,
        retry_at: datetime | None,
    ) -> bool:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(SourceORM)
                .where(
                    SourceORM.id == source_id,
                    SourceORM.processing_status == "PENDING",
                    SourceORM.processing_claim_owner == owner,
                )
                .values(
                    processing_status="FAILED",
                    processing_error=error_code,
                    processed_at=now if retry_at is None else None,
                    processing_claim_owner=None,
                    processing_lease_expires_at=None,
                    processing_heartbeat_at=None,
                    next_processing_attempt_at=retry_at,
                )
            ),
        )
        return result.rowcount == 1
