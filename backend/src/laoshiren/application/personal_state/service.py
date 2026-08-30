from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from laoshiren.application.personal_state import write_ops
from laoshiren.application.personal_state.dto import (
    ActiveThingDTO,
    BlockedThingDTO,
    BlockerDTO,
    MutationResultDTO,
    RecentThingDTO,
    StateMutationDTO,
    StateOverviewDTO,
    TaskDTO,
    ThingContextEntryDTO,
    ThingDateDTO,
    ThingDTO,
    ThingRelationDTO,
    TimelineEventDTO,
    UpcomingThingDTO,
)
from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.application.personal_state.prefetch import (
    ambiguous_thing_candidates,
    thing_prefetch_payload,
    thing_search_query_from_input,
)
from laoshiren.domain.personal_state.entities import (
    Blocker,
    StateMutation,
    Task,
    Thing,
    ThingContextEntry,
    ThingDate,
    ThingRelation,
    TimelineEvent,
    utc_now,
)
from laoshiren.domain.personal_state.exceptions import EntityNotFound, VersionConflict
from laoshiren.domain.personal_state.value_objects import (
    BlockerSeverity,
    DateCertainty,
    DatePrecision,
    TaskStatus,
    ThingDateType,
    ThingRelationType,
    ThingStatus,
)

UnitOfWorkFactory = Callable[[], PersonalStateUnitOfWork]


def to_thing_dto(thing: Thing) -> ThingDTO:
    return ThingDTO(
        id=thing.id,
        user_id=thing.user_id,
        name=thing.name,
        status=thing.status,
        current_stage=thing.current_stage,
        deadline_at=thing.deadline_at,
        merged_into_thing_id=thing.merged_into_thing_id,
        deleted_at=thing.deleted_at,
        version=thing.version,
        created_at=thing.created_at,
        updated_at=thing.updated_at,
    )


def to_task_dto(task: Task) -> TaskDTO:
    return TaskDTO(
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


def to_thing_date_dto(thing_date: ThingDate) -> ThingDateDTO:
    return ThingDateDTO(
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


def to_context_entry_dto(entry: ThingContextEntry) -> ThingContextEntryDTO:
    return ThingContextEntryDTO(
        id=entry.id,
        thing_id=entry.thing_id,
        label=entry.label,
        content=entry.content,
        source_id=entry.source_id,
        version=entry.version,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def to_timeline_dto(event: TimelineEvent) -> TimelineEventDTO:
    return TimelineEventDTO(
        id=event.id,
        thing_id=event.thing_id,
        event_type=event.event_type,
        title=event.title,
        summary=event.summary,
        occurred_at=event.occurred_at,
        source_id=event.source_id,
        mutation_id=event.mutation_id,
        metadata=event.metadata,
        created_at=event.created_at,
    )


def to_blocker_dto(blocker: Blocker) -> BlockerDTO:
    return BlockerDTO(
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


def to_relation_dto(relation: ThingRelation) -> ThingRelationDTO:
    return ThingRelationDTO(
        from_thing_id=relation.from_thing_id,
        to_thing_id=relation.to_thing_id,
        relation_type=relation.relation_type,
        note=relation.note,
        created_at=relation.created_at,
    )


def to_mutation_dto(mutation: StateMutation) -> StateMutationDTO:
    return StateMutationDTO(
        id=mutation.id,
        thing_id=mutation.thing_id,
        action_id=mutation.action_id,
        mutation_type=mutation.mutation_type,
        target_type=mutation.target_type,
        target_id=mutation.target_id,
        before=mutation.before,
        after=mutation.after,
        reason=mutation.reason,
        source_id=mutation.source_id,
        created_at=mutation.created_at,
    )


class PersonalStateApplicationService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    @staticmethod
    async def _resolve_active_thing(
        unit_of_work: PersonalStateUnitOfWork, *, user_id: UUID, thing_id: UUID
    ) -> Thing:
        current_id = thing_id
        seen: set[UUID] = set()
        while True:
            if current_id in seen:
                raise RuntimeError("Thing merge redirect cycle detected.")
            seen.add(current_id)
            thing = await unit_of_work.things.get_including_deleted(
                user_id=user_id, thing_id=current_id
            )
            if thing is None or thing.deleted_at is not None:
                raise EntityNotFound("Thing was not found.")
            if thing.merged_into_thing_id is None:
                return thing
            current_id = thing.merged_into_thing_id

    async def get_thing(self, *, user_id: UUID, thing_id: UUID) -> ThingDTO:
        async with self._unit_of_work_factory() as unit_of_work:
            thing = await unit_of_work.things.get_including_deleted(
                user_id=user_id, thing_id=thing_id
            )
            if thing is None or thing.deleted_at is not None:
                raise EntityNotFound("Thing was not found.")
            return to_thing_dto(thing)

    async def get_thing_context_snapshot(
        self, *, user_id: UUID, thing_id: UUID
    ) -> dict[str, object]:
        async with self._unit_of_work_factory() as unit_of_work:
            thing = await self._resolve_active_thing(
                unit_of_work, user_id=user_id, thing_id=thing_id
            )
            resolved_id = thing.id
            tasks = await unit_of_work.tasks.list_for_thing(user_id=user_id, thing_id=resolved_id)
            dates = await unit_of_work.dates.list_for_thing(
                user_id=user_id, thing_id=resolved_id, limit=100
            )
            blockers = await unit_of_work.blockers.list_for_thing(
                user_id=user_id, thing_id=resolved_id
            )
            entries = await unit_of_work.context_entries.list_for_thing(
                user_id=user_id, thing_id=resolved_id
            )
            payload: dict[str, object] = {
                "thing": {
                    "id": str(thing.id),
                    "name": thing.name,
                    "status": thing.status.value,
                    "current_stage": thing.current_stage,
                    "version": thing.version,
                    "deadline_at": thing.deadline_at.isoformat() if thing.deadline_at else None,
                },
                "context_entries": [
                    {
                        "id": str(entry.id),
                        "label": entry.label,
                        "content": entry.content,
                        "version": entry.version,
                    }
                    for entry in entries
                ],
                "tasks": [
                    {
                        "id": str(task.id),
                        "title": task.title,
                        "status": task.status.value,
                        "version": task.version,
                    }
                    for task in tasks
                ],
                "dates": [
                    {
                        "id": str(date.id),
                        "kind": date.kind.value,
                        "value": date.value.isoformat(),
                        "certainty": date.certainty.value,
                        "is_primary": date.is_primary,
                        "version": date.version,
                    }
                    for date in dates
                ],
                "open_blockers": [
                    {
                        "id": str(blocker.id),
                        "description": blocker.description,
                        "severity": blocker.severity.value,
                        "version": blocker.version,
                    }
                    for blocker in blockers
                    if blocker.status.value == "OPEN"
                ],
            }
            if resolved_id != thing_id:
                payload["requested_thing_id"] = str(thing_id)
                payload["resolved_thing_id"] = str(resolved_id)
            return payload

    async def get_things(
        self,
        *,
        user_id: UUID,
        status: ThingStatus | None = None,
        query: str | None = None,
        cursor: UUID | None = None,
        limit: int = 50,
    ) -> list[ThingDTO]:
        if not 1 <= limit <= 100:
            raise ValueError("Thing list limit must be between 1 and 100.")
        async with self._unit_of_work_factory() as unit_of_work:
            things = await unit_of_work.things.list_for_user(
                user_id=user_id,
                status=status,
                query=query.strip() if query else None,
                cursor=cursor,
                limit=limit,
            )
            return [to_thing_dto(thing) for thing in things]

    async def get_tasks(self, *, user_id: UUID, thing_id: UUID) -> list[TaskDTO]:
        async with self._unit_of_work_factory() as unit_of_work:
            tasks = await unit_of_work.tasks.list_for_thing(user_id=user_id, thing_id=thing_id)
            return [to_task_dto(task) for task in tasks]

    async def get_standalone_tasks(self, *, user_id: UUID) -> list[TaskDTO]:
        async with self._unit_of_work_factory() as unit_of_work:
            tasks = await unit_of_work.tasks.list_standalone(user_id=user_id)
            return [to_task_dto(task) for task in tasks]

    async def get_dates(
        self, *, user_id: UUID, thing_id: UUID, limit: int = 100
    ) -> list[ThingDateDTO]:
        if not 1 <= limit <= 100:
            raise ValueError("Date list limit must be between 1 and 100.")
        async with self._unit_of_work_factory() as unit_of_work:
            thing = await unit_of_work.things.get(user_id=user_id, thing_id=thing_id)
            if thing is None:
                raise EntityNotFound("Thing was not found.")
            dates = await unit_of_work.dates.list_for_thing(
                user_id=user_id, thing_id=thing_id, limit=limit
            )
            return [to_thing_date_dto(thing_date) for thing_date in dates]

    async def get_context_entries(
        self, *, user_id: UUID, thing_id: UUID
    ) -> list[ThingContextEntryDTO]:
        async with self._unit_of_work_factory() as unit_of_work:
            if await unit_of_work.things.get(user_id=user_id, thing_id=thing_id) is None:
                raise EntityNotFound("Thing was not found.")
            entries = await unit_of_work.context_entries.list_for_thing(
                user_id=user_id, thing_id=thing_id
            )
            return [to_context_entry_dto(entry) for entry in entries]

    async def set_thing_context(
        self,
        *,
        user_id: UUID,
        thing_id: UUID,
        label: str,
        content: str,
        entry_id: UUID | None,
        expected_version: int | None,
        source_id: UUID | None,
        action_id: str,
        idempotency_key: str,
        reason: str,
        run_id: UUID | None = None,
    ) -> MutationResultDTO:
        async with self._unit_of_work_factory() as unit_of_work:
            outcome = await write_ops.apply_set_thing_context(
                unit_of_work,
                user_id=user_id,
                thing_id=thing_id,
                label=label,
                content=content,
                entry_id=entry_id,
                expected_version=expected_version,
                source_id=source_id,
                action_id=action_id,
                idempotency_key=idempotency_key,
                reason=reason,
                run_id=run_id,
            )
            await unit_of_work.commit()
            return write_ops.mutation_result_from_outcome(outcome)

    async def get_timeline(
        self,
        *,
        user_id: UUID,
        thing_id: UUID,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[TimelineEventDTO]:
        if not 1 <= limit <= 100:
            raise ValueError("Timeline limit must be between 1 and 100.")
        normalized_event_type = event_type.strip() if event_type else None
        async with self._unit_of_work_factory() as unit_of_work:
            thing = await unit_of_work.things.get(user_id=user_id, thing_id=thing_id)
            if thing is None:
                raise EntityNotFound("Thing was not found.")
            events = await unit_of_work.audit.list_timeline(
                user_id=user_id,
                thing_id=thing_id,
                event_type=normalized_event_type,
                limit=limit,
            )
            return [to_timeline_dto(event) for event in events]

    async def get_state_history(
        self, *, user_id: UUID, thing_id: UUID, limit: int = 50
    ) -> list[StateMutationDTO]:
        if not 1 <= limit <= 100:
            raise ValueError("State history limit must be between 1 and 100.")
        async with self._unit_of_work_factory() as unit_of_work:
            if await unit_of_work.things.get(user_id=user_id, thing_id=thing_id) is None:
                raise EntityNotFound("Thing was not found.")
            mutations = await unit_of_work.audit.list_mutations(
                user_id=user_id, thing_id=thing_id, limit=limit
            )
            return [to_mutation_dto(mutation) for mutation in mutations]

    async def get_blockers(self, *, user_id: UUID, thing_id: UUID) -> list[BlockerDTO]:
        async with self._unit_of_work_factory() as unit_of_work:
            if await unit_of_work.things.get(user_id=user_id, thing_id=thing_id) is None:
                raise EntityNotFound("Thing was not found.")
            blockers = await unit_of_work.blockers.list_for_thing(
                user_id=user_id, thing_id=thing_id
            )
            return [to_blocker_dto(blocker) for blocker in blockers]

    async def get_relations(self, *, user_id: UUID, thing_id: UUID) -> list[ThingRelationDTO]:
        async with self._unit_of_work_factory() as unit_of_work:
            if await unit_of_work.things.get(user_id=user_id, thing_id=thing_id) is None:
                raise EntityNotFound("Thing was not found.")
            relations = await unit_of_work.relations.list_for_thing(
                user_id=user_id, thing_id=thing_id
            )
            return [to_relation_dto(relation) for relation in relations]

    async def update_thing(
        self,
        *,
        user_id: UUID,
        thing_id: UUID,
        expected_version: int,
        name: str | None,
        status: ThingStatus | None,
        current_stage: str | None,
        update_current_stage: bool,
        action_id: str,
        idempotency_key: str,
        reason: str,
        run_id: UUID | None = None,
    ) -> ThingDTO:
        if name is None and status is None and not update_current_stage:
            raise ValueError("At least one editable Thing field must be provided.")
        async with self._unit_of_work_factory() as unit_of_work:
            previous = await unit_of_work.audit.get_mutation(
                user_id=user_id, idempotency_key=idempotency_key
            )
            if previous is not None:
                thing = await unit_of_work.things.get(user_id=user_id, thing_id=thing_id)
                if thing is None:
                    raise RuntimeError("Idempotent Thing update points to a missing Thing.")
                return to_thing_dto(thing)

            thing = await unit_of_work.things.get(user_id=user_id, thing_id=thing_id)
            if thing is None:
                raise EntityNotFound("Thing was not found.")
            if thing.version != expected_version:
                raise VersionConflict("Thing version is stale.")
            before: dict[str, object] = {
                "name": thing.name,
                "status": thing.status.value,
                "current_stage": thing.current_stage,
                "version": thing.version,
            }
            thing.revise(
                name=name,
                status=status,
                current_stage=current_stage,
                update_current_stage=update_current_stage,
            )
            if not await unit_of_work.things.update(thing, expected_version=expected_version):
                raise VersionConflict("Thing was updated concurrently.")
            mutation = StateMutation(
                user_id=user_id,
                thing_id=thing.id,
                run_id=run_id,
                action_id=action_id,
                mutation_type="THING_UPDATED",
                target_type="THING",
                target_id=thing.id,
                before=before,
                after={
                    "name": thing.name,
                    "status": thing.status.value,
                    "current_stage": thing.current_stage,
                    "version": thing.version,
                },
                reason=reason,
                idempotency_key=idempotency_key,
            )
            await unit_of_work.audit.add_mutation(mutation)
            await unit_of_work.flush()
            await unit_of_work.audit.add_timeline_event(
                TimelineEvent(
                    user_id=user_id,
                    thing_id=thing.id,
                    event_type="THING_UPDATED",
                    title=f"更新事务：{thing.name}",
                    occurred_at=thing.updated_at,
                    mutation_id=mutation.id,
                )
            )
            await unit_of_work.commit()
            return to_thing_dto(thing)

    async def create_thing(
        self,
        *,
        user_id: UUID,
        name: str,
        action_id: str,
        idempotency_key: str,
        reason: str,
        run_id: UUID | None = None,
    ) -> ThingDTO:
        async with self._unit_of_work_factory() as unit_of_work:
            outcome = await write_ops.apply_create_thing(
                unit_of_work,
                user_id=user_id,
                name=name,
                action_id=action_id,
                idempotency_key=idempotency_key,
                reason=reason,
                run_id=run_id,
            )
            await unit_of_work.commit()
            thing = await unit_of_work.things.get(
                user_id=user_id, thing_id=UUID(str(outcome.data["id"]))
            )
            if thing is None:
                raise RuntimeError("Thing creation did not persist.")
            return to_thing_dto(thing)

    async def create_task(
        self,
        *,
        user_id: UUID,
        thing_id: UUID | None,
        title: str,
        due_at: datetime | None = None,
        recurrence_interval_days: int | None = None,
        action_id: str,
        idempotency_key: str,
        reason: str,
        run_id: UUID | None = None,
    ) -> TaskDTO:
        async with self._unit_of_work_factory() as unit_of_work:
            outcome = await write_ops.apply_create_task(
                unit_of_work,
                user_id=user_id,
                thing_id=thing_id,
                title=title,
                due_at=due_at,
                recurrence_interval_days=recurrence_interval_days,
                action_id=action_id,
                idempotency_key=idempotency_key,
                reason=reason,
                run_id=run_id,
            )
            await unit_of_work.commit()
            task = await unit_of_work.tasks.get(
                user_id=user_id, task_id=UUID(str(outcome.data["id"]))
            )
            if task is None:
                raise RuntimeError("Task creation did not persist.")
            return to_task_dto(task)

    async def complete_task(
        self,
        *,
        user_id: UUID,
        task_id: UUID,
        expected_version: int,
        action_id: str,
        idempotency_key: str,
        reason: str,
        run_id: UUID | None = None,
    ) -> MutationResultDTO:
        async with self._unit_of_work_factory() as unit_of_work:
            outcome = await write_ops.apply_complete_task(
                unit_of_work,
                user_id=user_id,
                task_id=task_id,
                expected_version=expected_version,
                action_id=action_id,
                idempotency_key=idempotency_key,
                reason=reason,
                run_id=run_id,
            )
            await unit_of_work.commit()
            return write_ops.mutation_result_from_outcome(outcome)

    async def set_deadline(
        self,
        *,
        user_id: UUID,
        thing_id: UUID,
        kind: ThingDateType,
        value: datetime,
        timezone_name: str,
        precision: DatePrecision,
        certainty: DateCertainty,
        is_primary: bool,
        expected_version: int,
        action_id: str,
        idempotency_key: str,
        reason: str,
        label: str | None = None,
        run_id: UUID | None = None,
        source_id: UUID | None = None,
    ) -> MutationResultDTO:
        async with self._unit_of_work_factory() as unit_of_work:
            outcome = await write_ops.apply_set_deadline(
                unit_of_work,
                user_id=user_id,
                thing_id=thing_id,
                kind=kind,
                value=value,
                timezone_name=timezone_name,
                precision=precision,
                certainty=certainty,
                is_primary=is_primary,
                expected_version=expected_version,
                action_id=action_id,
                idempotency_key=idempotency_key,
                reason=reason,
                label=label,
                run_id=run_id,
                source_id=source_id,
            )
            await unit_of_work.commit()
            return write_ops.mutation_result_from_outcome(outcome)

    async def transition_task(
        self,
        *,
        user_id: UUID,
        task_id: UUID,
        target_status: TaskStatus,
        expected_version: int,
        action_id: str,
        idempotency_key: str,
        reason: str,
    ) -> MutationResultDTO:
        async with self._unit_of_work_factory() as unit_of_work:
            outcome = await write_ops.apply_transition_task(
                unit_of_work,
                user_id=user_id,
                task_id=task_id,
                target_status=target_status,
                expected_version=expected_version,
                action_id=action_id,
                idempotency_key=idempotency_key,
                reason=reason,
            )
            await unit_of_work.commit()
            return write_ops.mutation_result_from_outcome(outcome)

    async def update_date(
        self,
        *,
        user_id: UUID,
        date_id: UUID,
        value: datetime,
        timezone_name: str,
        precision: DatePrecision,
        certainty: DateCertainty,
        is_primary: bool,
        expected_version: int,
        expected_thing_version: int,
        action_id: str,
        idempotency_key: str,
        reason: str,
    ) -> MutationResultDTO:
        async with self._unit_of_work_factory() as unit_of_work:
            outcome = await write_ops.apply_update_date(
                unit_of_work,
                user_id=user_id,
                date_id=date_id,
                value=value,
                timezone_name=timezone_name,
                precision=precision,
                certainty=certainty,
                is_primary=is_primary,
                expected_version=expected_version,
                expected_thing_version=expected_thing_version,
                action_id=action_id,
                idempotency_key=idempotency_key,
                reason=reason,
            )
            await unit_of_work.commit()
            return write_ops.mutation_result_from_outcome(outcome)

    async def create_blocker(
        self,
        *,
        user_id: UUID,
        thing_id: UUID,
        description: str,
        severity: BlockerSeverity,
        task_id: UUID | None,
        source_id: UUID | None,
        action_id: str,
        idempotency_key: str,
        reason: str,
    ) -> BlockerDTO:
        async with self._unit_of_work_factory() as unit_of_work:
            outcome = await write_ops.apply_create_blocker(
                unit_of_work,
                user_id=user_id,
                thing_id=thing_id,
                description=description,
                severity=severity,
                task_id=task_id,
                source_id=source_id,
                action_id=action_id,
                idempotency_key=idempotency_key,
                reason=reason,
            )
            await unit_of_work.commit()
            blocker = await unit_of_work.blockers.get(
                user_id=user_id, blocker_id=UUID(str(outcome.data["id"]))
            )
            if blocker is None:
                raise RuntimeError("Blocker creation did not persist.")
            return to_blocker_dto(blocker)

    async def resolve_blocker(
        self,
        *,
        user_id: UUID,
        blocker_id: UUID,
        expected_version: int,
        action_id: str,
        idempotency_key: str,
        reason: str,
    ) -> MutationResultDTO:
        async with self._unit_of_work_factory() as unit_of_work:
            outcome = await write_ops.apply_resolve_blocker(
                unit_of_work,
                user_id=user_id,
                blocker_id=blocker_id,
                expected_version=expected_version,
                action_id=action_id,
                idempotency_key=idempotency_key,
                reason=reason,
            )
            await unit_of_work.commit()
            return write_ops.mutation_result_from_outcome(outcome)

    async def add_relation(
        self,
        *,
        user_id: UUID,
        from_thing_id: UUID,
        to_thing_id: UUID,
        relation_type: ThingRelationType,
        note: str | None,
        action_id: str,
        idempotency_key: str,
        reason: str,
    ) -> bool:
        async with self._unit_of_work_factory() as unit_of_work:
            if (
                await unit_of_work.audit.get_mutation(
                    user_id=user_id, idempotency_key=idempotency_key
                )
                is not None
            ):
                return False
            for thing_id in (from_thing_id, to_thing_id):
                if await unit_of_work.things.get(user_id=user_id, thing_id=thing_id) is None:
                    raise EntityNotFound("Related Thing was not found.")
            relation = ThingRelation(
                from_thing_id=from_thing_id,
                to_thing_id=to_thing_id,
                relation_type=relation_type,
                note=note.strip() if note else None,
            )
            created = await unit_of_work.relations.add(relation)
            mutation = StateMutation(
                user_id=user_id,
                thing_id=from_thing_id,
                action_id=action_id,
                mutation_type="THING_RELATION_ADDED",
                target_type="THING",
                target_id=to_thing_id,
                after={"relation_type": relation_type.value, "created": created},
                reason=reason,
                idempotency_key=idempotency_key,
            )
            await unit_of_work.audit.add_mutation(mutation)
            await unit_of_work.commit()
            return created

    async def get_state_overview(
        self,
        *,
        user_id: UUID,
        now: datetime | None = None,
        upcoming_days: int = 7,
        upcoming_limit: int = 8,
        blocked_limit: int = 5,
        active_limit: int = 8,
        recent_limit: int = 5,
    ) -> StateOverviewDTO:
        current = now or utc_now()
        limits = (upcoming_days, upcoming_limit, blocked_limit, active_limit, recent_limit)
        if any(value <= 0 for value in limits):
            raise ValueError("State overview limits must be positive.")
        window_end = current + timedelta(days=upcoming_days)
        async with self._unit_of_work_factory() as unit_of_work:
            upcoming_things = await unit_of_work.things.list_upcoming(
                user_id=user_id, now=current, window_end=window_end, limit=upcoming_limit
            )
            active_things = await unit_of_work.things.list_active(
                user_id=user_id, limit=active_limit
            )
            recent_things = await unit_of_work.things.list_recent(
                user_id=user_id, limit=recent_limit
            )
            open_blockers = await unit_of_work.blockers.list_open(
                user_id=user_id, limit=blocked_limit
            )
            counted_ids = [thing.id for thing in (*upcoming_things, *active_things)]
            open_counts = (
                await unit_of_work.tasks.count_open(user_id=user_id, thing_ids=counted_ids)
                if counted_ids
                else {}
            )

        upcoming = tuple(
            UpcomingThingDTO(
                thing_id=thing.id,
                name=thing.name,
                deadline_at=thing.deadline_at,
                open_task_count=open_counts.get(thing.id, 0),
            )
            for thing in upcoming_things
            if thing.deadline_at is not None
        )
        active = tuple(
            ActiveThingDTO(
                thing_id=thing.id,
                name=thing.name,
                current_stage=thing.current_stage,
                open_task_count=open_counts.get(thing.id, 0),
            )
            for thing in active_things
        )
        blocked = tuple(
            BlockedThingDTO(
                thing_id=blocker.thing_id,
                thing_name=thing_name,
                description=blocker.description,
                severity=blocker.severity,
            )
            for blocker, thing_name in open_blockers
        )
        recent = tuple(
            RecentThingDTO(
                thing_id=thing.id,
                name=thing.name,
                status=thing.status,
                updated_at=thing.updated_at,
            )
            for thing in recent_things
        )
        return StateOverviewDTO(upcoming=upcoming, blocked=blocked, active=active, recent=recent)

    async def get_agent_thing_prefetch(
        self,
        *,
        user_id: UUID,
        active_thing_id: UUID | None = None,
        query: str | None = None,
        candidate_limit: int = 5,
    ) -> dict[str, object]:
        """Bounded Thing prefetch for Executive context (Agent 设计 §13.1)."""
        if candidate_limit <= 0:
            raise ValueError("Thing prefetch candidate limit must be positive.")
        if active_thing_id is not None:
            return await self._build_thing_prefetch(
                user_id=user_id, thing_id=active_thing_id, match_reason="active_thread"
            )
        normalized = (query or "").strip()
        if len(normalized) < 2:
            return {}
        search_query = thing_search_query_from_input(normalized)
        if len(search_query) < 2:
            return {}
        candidates = await self.get_things(
            user_id=user_id, query=search_query, limit=candidate_limit
        )
        if len(candidates) == 1:
            return await self._build_thing_prefetch(
                user_id=user_id,
                thing_id=candidates[0].id,
                match_reason="query_match",
            )
        if len(candidates) > 1:
            return ambiguous_thing_candidates(candidates)
        return {}

    async def _build_thing_prefetch(
        self, *, user_id: UUID, thing_id: UUID, match_reason: str
    ) -> dict[str, object]:
        thing = await self.get_thing(user_id=user_id, thing_id=thing_id)
        resolved_id = thing.merged_into_thing_id or thing.id
        tasks = await self.get_tasks(user_id=user_id, thing_id=resolved_id)
        blockers = await self.get_blockers(user_id=user_id, thing_id=resolved_id)
        dates = await self.get_dates(user_id=user_id, thing_id=resolved_id)
        return thing_prefetch_payload(
            thing=thing,
            tasks=tasks,
            blockers=blockers,
            dates=dates,
            match_reason=match_reason,
        )

    async def merge_things(
        self,
        *,
        user_id: UUID,
        canonical_thing_id: UUID,
        duplicate_thing_id: UUID,
        expected_canonical_version: int,
        expected_duplicate_version: int,
        action_id: str,
        idempotency_key: str,
        reason: str,
        run_id: UUID | None = None,
    ) -> MutationResultDTO:
        async with self._unit_of_work_factory() as unit_of_work:
            outcome = await write_ops.apply_merge_things(
                unit_of_work,
                user_id=user_id,
                canonical_thing_id=canonical_thing_id,
                duplicate_thing_id=duplicate_thing_id,
                expected_canonical_version=expected_canonical_version,
                expected_duplicate_version=expected_duplicate_version,
                action_id=action_id,
                idempotency_key=idempotency_key,
                reason=reason,
                run_id=run_id,
            )
            await unit_of_work.commit()
            return write_ops.mutation_result_from_outcome(outcome)

    async def archive_thing(
        self,
        *,
        user_id: UUID,
        thing_id: UUID,
        expected_version: int,
        action_id: str,
        idempotency_key: str,
        reason: str,
        run_id: UUID | None = None,
    ) -> MutationResultDTO:
        return await self._change_archive(
            user_id=user_id,
            thing_id=thing_id,
            expected_version=expected_version,
            action_id=action_id,
            idempotency_key=idempotency_key,
            reason=reason,
            run_id=run_id,
            archive=True,
        )

    async def unarchive_thing(
        self,
        *,
        user_id: UUID,
        thing_id: UUID,
        expected_version: int,
        action_id: str,
        idempotency_key: str,
        reason: str,
        run_id: UUID | None = None,
    ) -> MutationResultDTO:
        return await self._change_archive(
            user_id=user_id,
            thing_id=thing_id,
            expected_version=expected_version,
            action_id=action_id,
            idempotency_key=idempotency_key,
            reason=reason,
            run_id=run_id,
            archive=False,
        )

    async def _change_archive(
        self,
        *,
        user_id: UUID,
        thing_id: UUID,
        expected_version: int,
        action_id: str,
        idempotency_key: str,
        reason: str,
        run_id: UUID | None,
        archive: bool,
    ) -> MutationResultDTO:
        async with self._unit_of_work_factory() as unit_of_work:
            outcome = await write_ops.apply_change_archive(
                unit_of_work,
                user_id=user_id,
                thing_id=thing_id,
                expected_version=expected_version,
                action_id=action_id,
                idempotency_key=idempotency_key,
                reason=reason,
                run_id=run_id,
                archive=archive,
            )
            await unit_of_work.commit()
            return write_ops.mutation_result_from_outcome(outcome)

    async def delete_thing(
        self,
        *,
        user_id: UUID,
        thing_id: UUID,
        expected_version: int,
        action_id: str,
        idempotency_key: str,
        reason: str,
        run_id: UUID | None = None,
    ) -> MutationResultDTO:
        async with self._unit_of_work_factory() as unit_of_work:
            outcome = await write_ops.apply_delete_thing(
                unit_of_work,
                user_id=user_id,
                thing_id=thing_id,
                expected_version=expected_version,
                action_id=action_id,
                idempotency_key=idempotency_key,
                reason=reason,
                run_id=run_id,
            )
            await unit_of_work.commit()
            return write_ops.mutation_result_from_outcome(outcome)
