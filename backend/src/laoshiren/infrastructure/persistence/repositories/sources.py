from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
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
