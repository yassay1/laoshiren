from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from laoshiren.domain.personal_state.entities import (
    Blocker,
    StateMutation,
    Task,
    Thing,
    ThingContextEntry,
    ThingDate,
    ThingRelation,
    TimelineEvent,
)
from laoshiren.domain.personal_state.value_objects import (
    BlockerStatus,
    TaskStatus,
    ThingDateType,
    ThingStatus,
)
from laoshiren.infrastructure.persistence.orm.personal_state import (
    AutomationORM,
    BlockerORM,
    MemoryORM,
    NotificationOutboxORM,
    StateMutationORM,
    TaskORM,
    ThingContextEntryORM,
    ThingDateORM,
    ThingORM,
    ThingRelationORM,
    ThingSourceORM,
    ThreadORM,
    TimelineEventORM,
    UserORM,
)


def thing_to_domain(model: ThingORM) -> Thing:
    return Thing(
        id=model.id,
        user_id=model.user_id,
        name=model.name,
        status=model.status,
        current_stage=model.current_stage,
        deadline_at=model.deadline_at,
        archived_at=model.archived_at,
        merged_into_thing_id=model.merged_into_thing_id,
        deleted_at=model.deleted_at,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def task_to_domain(model: TaskORM) -> Task:
    return Task(
        id=model.id,
        user_id=model.user_id,
        thing_id=model.thing_id,
        title=model.title,
        status=model.status,
        version=model.version,
        completed_at=model.completed_at,
        due_at=model.due_at,
        recurrence_interval_days=model.recurrence_interval_days,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def mutation_to_domain(model: StateMutationORM) -> StateMutation:
    return StateMutation(
        id=model.id,
        user_id=model.user_id,
        thing_id=model.thing_id,
        run_id=model.run_id,
        action_id=model.action_id,
        mutation_type=model.mutation_type,
        target_type=model.target_type,
        target_id=model.target_id,
        before=model.before,
        after=model.after,
        reason=model.reason,
        source_id=model.source_id,
        idempotency_key=model.idempotency_key,
        created_at=model.created_at,
    )


def thing_date_to_domain(model: ThingDateORM) -> ThingDate:
    return ThingDate(
        id=model.id,
        thing_id=model.thing_id,
        kind=ThingDateType(model.kind),
        label=model.label,
        value=model.value,
        timezone_name=model.timezone_name,
        precision=model.precision,
        certainty=model.certainty,
        is_primary=model.is_primary,
        source_id=model.source_id,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def context_entry_to_domain(model: ThingContextEntryORM) -> ThingContextEntry:
    return ThingContextEntry(
        id=model.id,
        thing_id=model.thing_id,
        label=model.label,
        content=model.content,
        source_id=model.source_id,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def timeline_to_domain(model: TimelineEventORM) -> TimelineEvent:
    return TimelineEvent(
        id=model.id,
        user_id=model.user_id,
        thing_id=model.thing_id,
        event_type=model.event_type,
        title=model.title,
        summary=model.summary,
        occurred_at=model.occurred_at,
        source_id=model.source_id,
        mutation_id=model.mutation_id,
        metadata=model.metadata_,
        created_at=model.created_at,
    )


def blocker_to_domain(model: BlockerORM) -> Blocker:
    return Blocker(
        id=model.id,
        thing_id=model.thing_id,
        task_id=model.task_id,
        description=model.description,
        severity=model.severity,
        status=model.status,
        blocked_since=model.blocked_since,
        resolved_at=model.resolved_at,
        source_id=model.source_id,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def relation_to_domain(model: ThingRelationORM) -> ThingRelation:
    return ThingRelation(
        from_thing_id=model.from_thing_id,
        to_thing_id=model.to_thing_id,
        relation_type=model.relation_type,
        note=model.note,
        created_at=model.created_at,
    )


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_exists(self, user_id: UUID) -> None:
        statement = insert(UserORM).values(id=user_id).on_conflict_do_nothing(index_elements=["id"])
        await self._session.execute(statement)


class SqlAlchemyThingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, thing: Thing) -> None:
        self._session.add(
            ThingORM(
                id=thing.id,
                user_id=thing.user_id,
                name=thing.name,
                status=thing.status,
                current_stage=thing.current_stage,
                deadline_at=thing.deadline_at,
                archived_at=thing.archived_at,
                merged_into_thing_id=thing.merged_into_thing_id,
                deleted_at=thing.deleted_at,
                version=thing.version,
                created_at=thing.created_at,
                updated_at=thing.updated_at,
            )
        )

    async def get(self, *, user_id: UUID, thing_id: UUID) -> Thing | None:
        statement = select(ThingORM).where(
            ThingORM.id == thing_id,
            ThingORM.user_id == user_id,
            ThingORM.deleted_at.is_(None),
        )
        model = await self._session.scalar(statement)
        return thing_to_domain(model) if model is not None else None

    async def get_including_deleted(self, *, user_id: UUID, thing_id: UUID) -> Thing | None:
        statement = select(ThingORM).where(ThingORM.id == thing_id, ThingORM.user_id == user_id)
        model = await self._session.scalar(statement)
        return thing_to_domain(model) if model is not None else None

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        status: ThingStatus | None,
        query: str | None,
        cursor: UUID | None,
        limit: int,
    ) -> list[Thing]:
        statement = select(ThingORM).where(
            ThingORM.user_id == user_id,
            ThingORM.archived_at.is_(None),
            ThingORM.merged_into_thing_id.is_(None),
            ThingORM.deleted_at.is_(None),
        )
        if status is not None:
            statement = statement.where(ThingORM.status == status)
        if query:
            statement = statement.where(ThingORM.name.ilike(f"%{query}%"))
        if cursor is not None:
            statement = statement.where(ThingORM.id < cursor)
        statement = statement.order_by(ThingORM.id.desc()).limit(limit)
        models = (await self._session.scalars(statement)).all()
        return [thing_to_domain(model) for model in models]

    async def update(self, thing: Thing, *, expected_version: int) -> bool:
        statement = (
            update(ThingORM)
            .where(ThingORM.id == thing.id, ThingORM.version == expected_version)
            .values(
                name=thing.name,
                status=thing.status,
                current_stage=thing.current_stage,
                deadline_at=thing.deadline_at,
                archived_at=thing.archived_at,
                merged_into_thing_id=thing.merged_into_thing_id,
                deleted_at=thing.deleted_at,
                version=thing.version,
                updated_at=thing.updated_at,
            )
        )
        result = cast(CursorResult[Any], await self._session.execute(statement))
        return result.rowcount == 1

    async def detach_tasks(self, *, thing_id: UUID) -> None:
        await self._session.execute(
            update(TaskORM).where(TaskORM.thing_id == thing_id).values(thing_id=None)
        )

    async def delete_owned_components(self, *, thing_id: UUID) -> None:
        await self._session.execute(
            delete(ThingContextEntryORM).where(ThingContextEntryORM.thing_id == thing_id)
        )
        await self._session.execute(delete(ThingDateORM).where(ThingDateORM.thing_id == thing_id))
        await self._session.execute(delete(BlockerORM).where(BlockerORM.thing_id == thing_id))
        await self._session.execute(
            delete(ThingSourceORM).where(ThingSourceORM.thing_id == thing_id)
        )
        await self._session.execute(
            delete(ThingRelationORM).where(
                (ThingRelationORM.from_thing_id == thing_id)
                | (ThingRelationORM.to_thing_id == thing_id)
            )
        )

    async def rebind_merged_references(
        self, *, duplicate_thing_id: UUID, canonical_thing_id: UUID
    ) -> None:
        # Current-state associations move to the canonical Thing. Historical audit,
        # timeline, and legacy relation rows intentionally keep their original ID so
        # provenance remains resolvable through the redirect tombstone.
        for model in (
            TaskORM,
            ThingDateORM,
            BlockerORM,
            ThingContextEntryORM,
            AutomationORM,
            NotificationOutboxORM,
            MemoryORM,
        ):
            await self._session.execute(
                update(model)
                .where(model.thing_id == duplicate_thing_id)
                .values(thing_id=canonical_thing_id)
            )
        await self._session.execute(
            update(ThreadORM)
            .where(ThreadORM.active_thing_id == duplicate_thing_id)
            .values(active_thing_id=canonical_thing_id)
        )
        source_rows = select(
            literal(canonical_thing_id),
            ThingSourceORM.source_id,
            ThingSourceORM.relation_type,
            ThingSourceORM.relevance,
            ThingSourceORM.created_at,
        ).where(ThingSourceORM.thing_id == duplicate_thing_id)
        await self._session.execute(
            insert(ThingSourceORM)
            .from_select(
                ["thing_id", "source_id", "relation_type", "relevance", "created_at"],
                source_rows,
            )
            .on_conflict_do_nothing(index_elements=["thing_id", "source_id"])
        )
        await self._session.execute(
            delete(ThingSourceORM).where(ThingSourceORM.thing_id == duplicate_thing_id)
        )

    async def list_upcoming(
        self, *, user_id: UUID, now: datetime, window_end: datetime, limit: int
    ) -> list[Thing]:
        statement = (
            select(ThingORM)
            .where(
                ThingORM.user_id == user_id,
                ThingORM.archived_at.is_(None),
                ThingORM.merged_into_thing_id.is_(None),
                ThingORM.deadline_at.is_not(None),
                ThingORM.deadline_at >= now,
                ThingORM.deadline_at <= window_end,
            )
            .order_by(ThingORM.deadline_at, ThingORM.id)
            .limit(limit)
        )
        models = (await self._session.scalars(statement)).all()
        return [thing_to_domain(model) for model in models]

    async def list_active(self, *, user_id: UUID, limit: int) -> list[Thing]:
        statement = (
            select(ThingORM)
            .where(
                ThingORM.user_id == user_id,
                ThingORM.archived_at.is_(None),
                ThingORM.merged_into_thing_id.is_(None),
                ThingORM.status == ThingStatus.ACTIVE,
            )
            .order_by(ThingORM.updated_at.desc(), ThingORM.id.desc())
            .limit(limit)
        )
        models = (await self._session.scalars(statement)).all()
        return [thing_to_domain(model) for model in models]

    async def list_recent(self, *, user_id: UUID, limit: int) -> list[Thing]:
        statement = (
            select(ThingORM)
            .where(
                ThingORM.user_id == user_id,
                ThingORM.archived_at.is_(None),
                ThingORM.merged_into_thing_id.is_(None),
            )
            .order_by(ThingORM.updated_at.desc(), ThingORM.id.desc())
            .limit(limit)
        )
        models = (await self._session.scalars(statement)).all()
        return [thing_to_domain(model) for model in models]


class SqlAlchemyThingDateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, thing_date: ThingDate) -> None:
        self._session.add(
            ThingDateORM(
                id=thing_date.id,
                thing_id=thing_date.thing_id,
                kind=thing_date.kind,
                label=thing_date.label,
                value=thing_date.value,
                timezone_name=thing_date.timezone_name,
                precision=thing_date.precision,
                certainty=thing_date.certainty,
                is_primary=thing_date.is_primary,
                source_id=thing_date.source_id,
                version=thing_date.version,
                created_at=thing_date.created_at,
                updated_at=thing_date.updated_at,
            )
        )

    async def unset_primary(self, *, thing_id: UUID, kind: ThingDateType) -> None:
        statement = (
            update(ThingDateORM)
            .where(
                ThingDateORM.thing_id == thing_id,
                ThingDateORM.kind == kind,
                ThingDateORM.is_primary.is_(True),
            )
            .values(is_primary=False)
        )
        await self._session.execute(statement)

    async def list_for_thing(self, *, user_id: UUID, thing_id: UUID, limit: int) -> list[ThingDate]:
        statement = (
            select(ThingDateORM)
            .join(ThingORM, ThingORM.id == ThingDateORM.thing_id)
            .where(ThingDateORM.thing_id == thing_id, ThingORM.user_id == user_id)
            .order_by(ThingDateORM.value, ThingDateORM.id)
            .limit(limit)
        )
        models = (await self._session.scalars(statement)).all()
        return [thing_date_to_domain(model) for model in models]

    async def get(self, *, user_id: UUID, date_id: UUID) -> ThingDate | None:
        model = await self._session.scalar(
            select(ThingDateORM)
            .join(ThingORM, ThingORM.id == ThingDateORM.thing_id)
            .where(ThingDateORM.id == date_id, ThingORM.user_id == user_id)
        )
        return thing_date_to_domain(model) if model is not None else None

    async def update(self, thing_date: ThingDate, *, expected_version: int) -> bool:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(ThingDateORM)
                .where(ThingDateORM.id == thing_date.id, ThingDateORM.version == expected_version)
                .values(
                    value=thing_date.value,
                    timezone_name=thing_date.timezone_name,
                    precision=thing_date.precision,
                    certainty=thing_date.certainty,
                    is_primary=thing_date.is_primary,
                    version=thing_date.version,
                    updated_at=thing_date.updated_at,
                )
            ),
        )
        return result.rowcount == 1


class SqlAlchemyThingContextEntryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entry: ThingContextEntry) -> None:
        self._session.add(
            ThingContextEntryORM(
                id=entry.id,
                thing_id=entry.thing_id,
                label=entry.label,
                content=entry.content,
                source_id=entry.source_id,
                version=entry.version,
                created_at=entry.created_at,
                updated_at=entry.updated_at,
            )
        )

    async def get(self, *, user_id: UUID, entry_id: UUID) -> ThingContextEntry | None:
        model = await self._session.scalar(
            select(ThingContextEntryORM)
            .join(ThingORM, ThingORM.id == ThingContextEntryORM.thing_id)
            .where(ThingContextEntryORM.id == entry_id, ThingORM.user_id == user_id)
        )
        return context_entry_to_domain(model) if model is not None else None

    async def list_for_thing(self, *, user_id: UUID, thing_id: UUID) -> list[ThingContextEntry]:
        models = (
            await self._session.scalars(
                select(ThingContextEntryORM)
                .join(ThingORM, ThingORM.id == ThingContextEntryORM.thing_id)
                .where(ThingContextEntryORM.thing_id == thing_id, ThingORM.user_id == user_id)
                .order_by(ThingContextEntryORM.updated_at.desc(), ThingContextEntryORM.id.desc())
            )
        ).all()
        return [context_entry_to_domain(model) for model in models]

    async def update(self, entry: ThingContextEntry, *, expected_version: int) -> bool:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(ThingContextEntryORM)
                .where(
                    ThingContextEntryORM.id == entry.id,
                    ThingContextEntryORM.version == expected_version,
                )
                .values(
                    label=entry.label,
                    content=entry.content,
                    version=entry.version,
                    updated_at=entry.updated_at,
                )
            ),
        )
        return result.rowcount == 1


class SqlAlchemyTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, task: Task) -> None:
        self._session.add(
            TaskORM(
                id=task.id,
                user_id=task.user_id,
                thing_id=task.thing_id,
                title=task.title,
                status=task.status,
                version=task.version,
                completed_at=task.completed_at,
                due_at=task.due_at,
                recurrence_interval_days=task.recurrence_interval_days,
                created_at=task.created_at,
                updated_at=task.updated_at,
            )
        )

    async def get(self, *, user_id: UUID, task_id: UUID) -> Task | None:
        statement = select(TaskORM).where(TaskORM.id == task_id, TaskORM.user_id == user_id)
        model = await self._session.scalar(statement)
        return task_to_domain(model) if model is not None else None

    async def list_for_thing(self, *, user_id: UUID, thing_id: UUID) -> list[Task]:
        statement = (
            select(TaskORM)
            .where(TaskORM.thing_id == thing_id, TaskORM.user_id == user_id)
            .order_by(TaskORM.created_at, TaskORM.id)
        )
        models = (await self._session.scalars(statement)).all()
        return [task_to_domain(model) for model in models]

    async def list_standalone(self, *, user_id: UUID) -> list[Task]:
        models = (
            await self._session.scalars(
                select(TaskORM)
                .where(TaskORM.user_id == user_id, TaskORM.thing_id.is_(None))
                .order_by(TaskORM.created_at, TaskORM.id)
            )
        ).all()
        return [task_to_domain(model) for model in models]

    async def update(self, task: Task, *, expected_version: int) -> bool:
        statement = (
            update(TaskORM)
            .where(TaskORM.id == task.id, TaskORM.version == expected_version)
            .values(
                status=task.status,
                version=task.version,
                completed_at=task.completed_at,
                due_at=task.due_at,
                recurrence_interval_days=task.recurrence_interval_days,
                updated_at=task.updated_at,
            )
        )
        result = cast(CursorResult[Any], await self._session.execute(statement))
        return result.rowcount == 1

    async def count_open(self, *, user_id: UUID, thing_ids: list[UUID]) -> dict[UUID, int]:
        if not thing_ids:
            return {}
        statement = (
            select(TaskORM.thing_id, func.count())
            .where(
                TaskORM.thing_id.in_(thing_ids),
                TaskORM.user_id == user_id,
                TaskORM.status == TaskStatus.TODO,
            )
            .group_by(TaskORM.thing_id)
        )
        rows = (await self._session.execute(statement)).all()
        return {row[0]: int(row[1]) for row in rows}


class SqlAlchemyAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_mutation(self, *, user_id: UUID, idempotency_key: str) -> StateMutation | None:
        statement = select(StateMutationORM).where(
            StateMutationORM.user_id == user_id,
            StateMutationORM.idempotency_key == idempotency_key,
        )
        model = await self._session.scalar(statement)
        return mutation_to_domain(model) if model is not None else None

    async def add_mutation(self, mutation: StateMutation) -> None:
        self._session.add(
            StateMutationORM(
                id=mutation.id,
                user_id=mutation.user_id,
                thing_id=mutation.thing_id,
                run_id=mutation.run_id,
                action_id=mutation.action_id,
                mutation_type=mutation.mutation_type,
                target_type=mutation.target_type,
                target_id=mutation.target_id,
                before=mutation.before,
                after=mutation.after,
                reason=mutation.reason,
                source_id=mutation.source_id,
                idempotency_key=mutation.idempotency_key,
                created_at=mutation.created_at,
            )
        )

    async def add_timeline_event(self, event: TimelineEvent) -> None:
        self._session.add(
            TimelineEventORM(
                id=event.id,
                user_id=event.user_id,
                thing_id=event.thing_id,
                event_type=event.event_type,
                title=event.title,
                summary=event.summary,
                occurred_at=event.occurred_at,
                source_id=event.source_id,
                mutation_id=event.mutation_id,
                metadata_=event.metadata,
                created_at=event.created_at,
            )
        )

    async def list_timeline(
        self,
        *,
        user_id: UUID,
        thing_id: UUID,
        event_type: str | None,
        limit: int,
    ) -> list[TimelineEvent]:
        statement = select(TimelineEventORM).where(
            TimelineEventORM.user_id == user_id,
            TimelineEventORM.thing_id == thing_id,
        )
        if event_type is not None:
            statement = statement.where(TimelineEventORM.event_type == event_type)
        statement = statement.order_by(
            TimelineEventORM.occurred_at.desc(), TimelineEventORM.id.desc()
        ).limit(limit)
        models = (await self._session.scalars(statement)).all()
        return [timeline_to_domain(model) for model in models]

    async def list_mutations(
        self, *, user_id: UUID, thing_id: UUID, limit: int
    ) -> list[StateMutation]:
        statement = (
            select(StateMutationORM)
            .where(
                StateMutationORM.user_id == user_id,
                StateMutationORM.thing_id == thing_id,
            )
            .order_by(StateMutationORM.created_at.desc(), StateMutationORM.id.desc())
            .limit(limit)
        )
        models = (await self._session.scalars(statement)).all()
        return [mutation_to_domain(model) for model in models]


class SqlAlchemyBlockerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, blocker: Blocker) -> None:
        self._session.add(
            BlockerORM(
                id=blocker.id,
                thing_id=blocker.thing_id,
                task_id=blocker.task_id,
                description=blocker.description,
                severity=blocker.severity,
                status=blocker.status,
                blocked_since=blocker.blocked_since,
                resolved_at=blocker.resolved_at,
                source_id=blocker.source_id,
                version=blocker.version,
                created_at=blocker.created_at,
                updated_at=blocker.updated_at,
            )
        )

    async def get(self, *, user_id: UUID, blocker_id: UUID) -> Blocker | None:
        model = await self._session.scalar(
            select(BlockerORM)
            .join(ThingORM, ThingORM.id == BlockerORM.thing_id)
            .where(BlockerORM.id == blocker_id, ThingORM.user_id == user_id)
        )
        return blocker_to_domain(model) if model is not None else None

    async def list_for_thing(self, *, user_id: UUID, thing_id: UUID) -> list[Blocker]:
        models = (
            await self._session.scalars(
                select(BlockerORM)
                .join(ThingORM, ThingORM.id == BlockerORM.thing_id)
                .where(BlockerORM.thing_id == thing_id, ThingORM.user_id == user_id)
                .order_by(BlockerORM.created_at.desc(), BlockerORM.id.desc())
            )
        ).all()
        return [blocker_to_domain(model) for model in models]

    async def update(self, blocker: Blocker, *, expected_version: int) -> bool:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(BlockerORM)
                .where(BlockerORM.id == blocker.id, BlockerORM.version == expected_version)
                .values(
                    status=blocker.status,
                    resolved_at=blocker.resolved_at,
                    version=blocker.version,
                    updated_at=blocker.updated_at,
                )
            ),
        )
        return result.rowcount == 1

    async def list_open(self, *, user_id: UUID, limit: int) -> list[tuple[Blocker, str]]:
        rows = (
            await self._session.execute(
                select(BlockerORM, ThingORM.name)
                .join(ThingORM, ThingORM.id == BlockerORM.thing_id)
                .where(
                    BlockerORM.status == BlockerStatus.OPEN,
                    ThingORM.user_id == user_id,
                    ThingORM.archived_at.is_(None),
                )
                .order_by(BlockerORM.blocked_since.desc(), BlockerORM.id.desc())
                .limit(limit)
            )
        ).all()
        return [(blocker_to_domain(blocker), name) for blocker, name in rows]


class SqlAlchemyThingRelationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, relation: ThingRelation) -> bool:
        statement = (
            insert(ThingRelationORM)
            .values(
                from_thing_id=relation.from_thing_id,
                to_thing_id=relation.to_thing_id,
                relation_type=relation.relation_type,
                note=relation.note,
                created_at=relation.created_at,
            )
            .on_conflict_do_nothing(
                index_elements=["from_thing_id", "to_thing_id", "relation_type"]
            )
            .returning(ThingRelationORM.to_thing_id)
        )
        return (await self._session.scalar(statement)) is not None

    async def list_for_thing(self, *, user_id: UUID, thing_id: UUID) -> list[ThingRelation]:
        models = (
            await self._session.scalars(
                select(ThingRelationORM)
                .join(ThingORM, ThingORM.id == ThingRelationORM.from_thing_id)
                .where(
                    ThingRelationORM.from_thing_id == thing_id,
                    ThingORM.user_id == user_id,
                )
                .order_by(ThingRelationORM.created_at, ThingRelationORM.to_thing_id)
            )
        ).all()
        return [relation_to_domain(model) for model in models]
