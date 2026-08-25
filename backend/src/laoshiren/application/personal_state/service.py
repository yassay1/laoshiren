from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from laoshiren.application.personal_state.dto import (
    ActiveThingDTO,
    BlockedThingDTO,
    BlockerDTO,
    MutationResultDTO,
    RecentThingDTO,
    StateMutationDTO,
    StateOverviewDTO,
    TaskDTO,
    ThingDateDTO,
    ThingDTO,
    ThingRelationDTO,
    TimelineEventDTO,
    UpcomingThingDTO,
)
from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.domain.personal_state.entities import (
    Blocker,
    StateMutation,
    Task,
    Thing,
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
        version=thing.version,
        created_at=thing.created_at,
        updated_at=thing.updated_at,
    )


def to_task_dto(task: Task) -> TaskDTO:
    return TaskDTO(
        id=task.id,
        thing_id=task.thing_id,
        title=task.title,
        status=task.status,
        version=task.version,
        completed_at=task.completed_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def to_thing_date_dto(thing_date: ThingDate) -> ThingDateDTO:
    return ThingDateDTO(
        id=thing_date.id,
        thing_id=thing_date.thing_id,
        kind=thing_date.kind,
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

    async def get_thing(self, *, user_id: UUID, thing_id: UUID) -> ThingDTO:
        async with self._unit_of_work_factory() as unit_of_work:
            thing = await unit_of_work.things.get(user_id=user_id, thing_id=thing_id)
            if thing is None:
                raise EntityNotFound("Thing was not found.")
            return to_thing_dto(thing)

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

    async def get_relations(
        self, *, user_id: UUID, thing_id: UUID
    ) -> list[ThingRelationDTO]:
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
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Thing name must not be empty.")
        async with self._unit_of_work_factory() as unit_of_work:
            previous = await unit_of_work.audit.get_mutation(
                user_id=user_id, idempotency_key=idempotency_key
            )
            if previous is not None:
                thing = await unit_of_work.things.get(user_id=user_id, thing_id=previous.target_id)
                if thing is None:
                    raise RuntimeError("Idempotent Thing creation points to a missing Thing.")
                return to_thing_dto(thing)

            await unit_of_work.users.ensure_exists(user_id)
            thing = Thing(user_id=user_id, name=normalized_name)
            await unit_of_work.things.add(thing)
            await unit_of_work.flush()
            mutation = StateMutation(
                user_id=user_id,
                thing_id=thing.id,
                run_id=run_id,
                action_id=action_id,
                mutation_type="THING_CREATED",
                target_type="THING",
                target_id=thing.id,
                after={
                    "name": thing.name,
                    "status": thing.status.value,
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
                    event_type="THING_CREATED",
                    title=f"创建事务：{thing.name}",
                    occurred_at=thing.created_at,
                    mutation_id=mutation.id,
                )
            )
            await unit_of_work.commit()
            return to_thing_dto(thing)

    async def create_task(
        self,
        *,
        user_id: UUID,
        thing_id: UUID,
        title: str,
        action_id: str,
        idempotency_key: str,
        reason: str,
        run_id: UUID | None = None,
    ) -> TaskDTO:
        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("Task title must not be empty.")
        async with self._unit_of_work_factory() as unit_of_work:
            previous = await unit_of_work.audit.get_mutation(
                user_id=user_id, idempotency_key=idempotency_key
            )
            if previous is not None:
                task = await unit_of_work.tasks.get(user_id=user_id, task_id=previous.target_id)
                if task is None:
                    raise RuntimeError("Idempotent Task creation points to a missing Task.")
                return to_task_dto(task)

            thing = await unit_of_work.things.get(user_id=user_id, thing_id=thing_id)
            if thing is None:
                raise EntityNotFound("Thing was not found.")
            task = Task(thing_id=thing.id, title=normalized_title)
            await unit_of_work.tasks.add(task)
            await unit_of_work.flush()
            mutation = StateMutation(
                user_id=user_id,
                thing_id=thing.id,
                run_id=run_id,
                action_id=action_id,
                mutation_type="TASK_CREATED",
                target_type="TASK",
                target_id=task.id,
                after={
                    "title": task.title,
                    "status": task.status.value,
                    "version": task.version,
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
                    event_type="TASK_CREATED",
                    title=f"创建任务：{task.title}",
                    occurred_at=task.created_at,
                    mutation_id=mutation.id,
                )
            )
            await unit_of_work.commit()
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
            previous = await unit_of_work.audit.get_mutation(
                user_id=user_id, idempotency_key=idempotency_key
            )
            if previous is not None:
                previous_version = previous.after.get("version")
                if not isinstance(previous_version, int):
                    raise RuntimeError("Stored mutation is missing a valid target version.")
                return MutationResultDTO(
                    mutation_id=previous.id,
                    target_id=previous.target_id,
                    target_version=previous_version,
                    replayed=True,
                )

            task = await unit_of_work.tasks.get(user_id=user_id, task_id=task_id)
            if task is None:
                raise EntityNotFound("Task was not found.")
            if task.version != expected_version:
                raise VersionConflict("Task version is stale.")

            before: dict[str, object] = {
                "status": task.status.value,
                "version": task.version,
            }
            task.complete()
            updated = await unit_of_work.tasks.update(task, expected_version=expected_version)
            if not updated:
                raise VersionConflict("Task was updated concurrently.")

            mutation = StateMutation(
                user_id=user_id,
                thing_id=task.thing_id,
                run_id=run_id,
                action_id=action_id,
                mutation_type="TASK_COMPLETED",
                target_type="TASK",
                target_id=task.id,
                before=before,
                after={"status": TaskStatus.DONE.value, "version": task.version},
                reason=reason,
                idempotency_key=idempotency_key,
            )
            timeline = TimelineEvent(
                user_id=user_id,
                thing_id=task.thing_id,
                event_type="TASK_COMPLETED",
                title=f"{task.title}已完成",
                occurred_at=task.completed_at or utc_now(),
                mutation_id=mutation.id,
            )
            await unit_of_work.audit.add_mutation(mutation)
            await unit_of_work.flush()
            await unit_of_work.audit.add_timeline_event(timeline)
            await unit_of_work.commit()
            return MutationResultDTO(
                mutation_id=mutation.id,
                target_id=task.id,
                target_version=task.version,
            )

    async def set_deadline(
        self,
        *,
        user_id: UUID,
        thing_id: UUID,
        kind: str,
        value: datetime,
        timezone_name: str,
        precision: DatePrecision,
        certainty: DateCertainty,
        is_primary: bool,
        expected_version: int,
        action_id: str,
        idempotency_key: str,
        reason: str,
        run_id: UUID | None = None,
    ) -> MutationResultDTO:
        if value.tzinfo is None:
            raise ValueError("Deadline must include timezone information.")
        if not kind.strip() or not timezone_name.strip():
            raise ValueError("Deadline kind and timezone must not be empty.")
        if is_primary and certainty is not DateCertainty.CONFIRMED:
            raise ValueError("Only a confirmed date can become the primary deadline.")

        async with self._unit_of_work_factory() as unit_of_work:
            previous = await unit_of_work.audit.get_mutation(
                user_id=user_id, idempotency_key=idempotency_key
            )
            if previous is not None:
                previous_version = previous.after.get("thing_version")
                if not isinstance(previous_version, int):
                    raise RuntimeError("Stored deadline mutation is missing Thing version.")
                return MutationResultDTO(
                    mutation_id=previous.id,
                    target_id=previous.target_id,
                    target_version=previous_version,
                    replayed=True,
                )

            thing = await unit_of_work.things.get(user_id=user_id, thing_id=thing_id)
            if thing is None:
                raise EntityNotFound("Thing was not found.")
            if thing.version != expected_version:
                raise VersionConflict("Thing version is stale.")

            previous_deadline = thing.deadline_at
            thing_date = ThingDate(
                thing_id=thing.id,
                kind=kind.strip(),
                value=value,
                timezone_name=timezone_name.strip(),
                precision=precision,
                certainty=certainty,
                is_primary=is_primary,
            )
            if is_primary:
                thing.set_primary_deadline(value)
                updated = await unit_of_work.things.update(thing, expected_version=expected_version)
                if not updated:
                    raise VersionConflict("Thing was updated concurrently.")
                await unit_of_work.dates.unset_primary(thing_id=thing.id, kind=thing_date.kind)

            await unit_of_work.dates.add(thing_date)
            await unit_of_work.flush()
            mutation = StateMutation(
                user_id=user_id,
                thing_id=thing.id,
                run_id=run_id,
                action_id=action_id,
                mutation_type="DEADLINE_SET",
                target_type="THING_DATE",
                target_id=thing_date.id,
                before={
                    "deadline_at": previous_deadline.isoformat()
                    if previous_deadline is not None
                    else None,
                    "thing_version": expected_version,
                },
                after={
                    "value": value.isoformat(),
                    "certainty": certainty.value,
                    "is_primary": is_primary,
                    "thing_version": thing.version,
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
                    event_type="DEADLINE_CHANGED" if is_primary else "IMPORTANT_DATE_ADDED",
                    title=f"设置日期：{thing_date.kind}",
                    occurred_at=utc_now(),
                    mutation_id=mutation.id,
                )
            )
            await unit_of_work.commit()
            return MutationResultDTO(
                mutation_id=mutation.id,
                target_id=thing_date.id,
                target_version=thing.version,
            )

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
            previous = await unit_of_work.audit.get_mutation(
                user_id=user_id, idempotency_key=idempotency_key
            )
            if previous is not None:
                version = previous.after.get("version")
                if not isinstance(version, int):
                    raise RuntimeError("Stored Task mutation is missing target version.")
                return MutationResultDTO(previous.id, previous.target_id, version, True)
            task = await unit_of_work.tasks.get(user_id=user_id, task_id=task_id)
            if task is None:
                raise EntityNotFound("Task was not found.")
            if task.version != expected_version:
                raise VersionConflict("Task version is stale.")
            before_status = task.status
            task.transition_to(target_status)
            if task.version == expected_version:
                raise ValueError("Task already has the requested status.")
            if not await unit_of_work.tasks.update(task, expected_version=expected_version):
                raise VersionConflict("Task was updated concurrently.")
            mutation = StateMutation(
                user_id=user_id,
                thing_id=task.thing_id,
                action_id=action_id,
                mutation_type="TASK_STATUS_CHANGED",
                target_type="TASK",
                target_id=task.id,
                before={"status": before_status.value, "version": expected_version},
                after={"status": task.status.value, "version": task.version},
                reason=reason,
                idempotency_key=idempotency_key,
            )
            await unit_of_work.audit.add_mutation(mutation)
            await unit_of_work.flush()
            await unit_of_work.audit.add_timeline_event(
                TimelineEvent(
                    user_id=user_id,
                    thing_id=task.thing_id,
                    event_type="TASK_COMPLETED"
                    if task.status is TaskStatus.DONE
                    else "TASK_STATUS_CHANGED",
                    title=f"任务状态变更：{task.title} → {task.status.value}",
                    occurred_at=task.updated_at,
                    mutation_id=mutation.id,
                )
            )
            await unit_of_work.commit()
            return MutationResultDTO(mutation.id, task.id, task.version)

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
            previous = await unit_of_work.audit.get_mutation(
                user_id=user_id, idempotency_key=idempotency_key
            )
            if previous is not None:
                version = previous.after.get("date_version")
                if not isinstance(version, int):
                    raise RuntimeError("Stored date mutation is missing target version.")
                return MutationResultDTO(previous.id, previous.target_id, version, True)
            thing_date = await unit_of_work.dates.get(user_id=user_id, date_id=date_id)
            if thing_date is None:
                raise EntityNotFound("ThingDate was not found.")
            if thing_date.version != expected_version:
                raise VersionConflict("ThingDate version is stale.")
            thing = await unit_of_work.things.get(
                user_id=user_id, thing_id=thing_date.thing_id
            )
            if thing is None:
                raise EntityNotFound("Thing was not found.")
            if thing.version != expected_thing_version:
                raise VersionConflict("Thing version is stale.")
            before: dict[str, object] = {
                "value": thing_date.value.isoformat(),
                "certainty": thing_date.certainty.value,
                "is_primary": thing_date.is_primary,
                "date_version": thing_date.version,
                "thing_version": thing.version,
            }
            was_primary = thing_date.is_primary
            thing_date.revise(
                value=value,
                timezone_name=timezone_name,
                precision=precision,
                certainty=certainty,
                is_primary=is_primary,
            )
            if is_primary:
                await unit_of_work.dates.unset_primary(
                    thing_id=thing.id, kind=thing_date.kind
                )
                thing.set_primary_deadline(value)
            elif was_primary:
                thing.deadline_at = None
                thing.touch()
            if thing.version != expected_thing_version and not await unit_of_work.things.update(
                thing, expected_version=expected_thing_version
            ):
                raise VersionConflict("Thing was updated concurrently.")
            if not await unit_of_work.dates.update(
                thing_date, expected_version=expected_version
            ):
                raise VersionConflict("ThingDate was updated concurrently.")
            mutation = StateMutation(
                user_id=user_id,
                thing_id=thing.id,
                action_id=action_id,
                mutation_type="DATE_UPDATED",
                target_type="THING_DATE",
                target_id=thing_date.id,
                before=before,
                after={
                    "value": thing_date.value.isoformat(),
                    "certainty": thing_date.certainty.value,
                    "is_primary": thing_date.is_primary,
                    "date_version": thing_date.version,
                    "thing_version": thing.version,
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
                    event_type="DEADLINE_CHANGED" if is_primary or was_primary else "DATE_CHANGED",
                    title=f"更新日期：{thing_date.kind}",
                    occurred_at=thing_date.updated_at,
                    mutation_id=mutation.id,
                )
            )
            await unit_of_work.commit()
            return MutationResultDTO(mutation.id, thing_date.id, thing_date.version)

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
        normalized = description.strip()
        if not normalized:
            raise ValueError("Blocker description must not be empty.")
        async with self._unit_of_work_factory() as unit_of_work:
            previous = await unit_of_work.audit.get_mutation(
                user_id=user_id, idempotency_key=idempotency_key
            )
            if previous is not None:
                blocker = await unit_of_work.blockers.get(
                    user_id=user_id, blocker_id=previous.target_id
                )
                if blocker is None:
                    raise RuntimeError("Idempotent Blocker creation points to missing data.")
                return to_blocker_dto(blocker)
            if await unit_of_work.things.get(user_id=user_id, thing_id=thing_id) is None:
                raise EntityNotFound("Thing was not found.")
            if task_id is not None:
                task = await unit_of_work.tasks.get(user_id=user_id, task_id=task_id)
                if task is None or task.thing_id != thing_id:
                    raise EntityNotFound("Task was not found in this Thing.")
            if source_id is not None and await unit_of_work.sources.get(
                user_id=user_id, source_id=source_id
            ) is None:
                raise EntityNotFound("Source was not found.")
            blocker = Blocker(
                thing_id=thing_id,
                task_id=task_id,
                description=normalized,
                severity=severity,
                source_id=source_id,
            )
            await unit_of_work.blockers.add(blocker)
            await unit_of_work.flush()
            mutation = StateMutation(
                user_id=user_id,
                thing_id=thing_id,
                action_id=action_id,
                mutation_type="BLOCKER_ADDED",
                target_type="BLOCKER",
                target_id=blocker.id,
                after={"status": blocker.status.value, "version": blocker.version},
                reason=reason,
                source_id=source_id,
                idempotency_key=idempotency_key,
            )
            await unit_of_work.audit.add_mutation(mutation)
            await unit_of_work.flush()
            await unit_of_work.audit.add_timeline_event(
                TimelineEvent(
                    user_id=user_id,
                    thing_id=thing_id,
                    event_type="BLOCKER_ADDED",
                    title=f"新增阻碍：{blocker.description}",
                    occurred_at=blocker.blocked_since,
                    source_id=source_id,
                    mutation_id=mutation.id,
                )
            )
            await unit_of_work.commit()
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
            previous = await unit_of_work.audit.get_mutation(
                user_id=user_id, idempotency_key=idempotency_key
            )
            if previous is not None:
                version = previous.after.get("version")
                if not isinstance(version, int):
                    raise RuntimeError("Stored Blocker mutation is missing target version.")
                return MutationResultDTO(previous.id, previous.target_id, version, True)
            blocker = await unit_of_work.blockers.get(
                user_id=user_id, blocker_id=blocker_id
            )
            if blocker is None:
                raise EntityNotFound("Blocker was not found.")
            if blocker.version != expected_version:
                raise VersionConflict("Blocker version is stale.")
            blocker.resolve()
            if not await unit_of_work.blockers.update(
                blocker, expected_version=expected_version
            ):
                raise VersionConflict("Blocker was updated concurrently.")
            mutation = StateMutation(
                user_id=user_id,
                thing_id=blocker.thing_id,
                action_id=action_id,
                mutation_type="BLOCKER_RESOLVED",
                target_type="BLOCKER",
                target_id=blocker.id,
                before={"status": "OPEN", "version": expected_version},
                after={"status": blocker.status.value, "version": blocker.version},
                reason=reason,
                idempotency_key=idempotency_key,
            )
            await unit_of_work.audit.add_mutation(mutation)
            await unit_of_work.flush()
            await unit_of_work.audit.add_timeline_event(
                TimelineEvent(
                    user_id=user_id,
                    thing_id=blocker.thing_id,
                    event_type="BLOCKER_RESOLVED",
                    title=f"解决阻碍：{blocker.description}",
                    occurred_at=blocker.resolved_at or utc_now(),
                    mutation_id=mutation.id,
                )
            )
            await unit_of_work.commit()
            return MutationResultDTO(mutation.id, blocker.id, blocker.version)

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
            if await unit_of_work.audit.get_mutation(
                user_id=user_id, idempotency_key=idempotency_key
            ) is not None:
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
            previous = await unit_of_work.audit.get_mutation(
                user_id=user_id, idempotency_key=idempotency_key
            )
            if previous is not None:
                version = previous.after.get("version")
                if not isinstance(version, int):
                    raise RuntimeError("Stored archive mutation is missing its target version.")
                return MutationResultDTO(
                    mutation_id=previous.id,
                    target_id=previous.target_id,
                    target_version=version,
                    replayed=True,
                )

            thing = await unit_of_work.things.get(user_id=user_id, thing_id=thing_id)
            if thing is None:
                raise EntityNotFound("Thing was not found.")
            if thing.version != expected_version:
                raise VersionConflict("Thing version is stale.")

            before: dict[str, object] = {
                "archived_at": (
                    thing.archived_at.isoformat() if thing.archived_at is not None else None
                ),
                "version": thing.version,
            }
            if archive:
                thing.archive()
                mutation_type = "THING_ARCHIVED"
                event_type = "THING_ARCHIVED"
                title = f"归档事务：{thing.name}"
            else:
                thing.unarchive()
                mutation_type = "THING_UNARCHIVED"
                event_type = "THING_UNARCHIVED"
                title = f"恢复事务：{thing.name}"
            if not await unit_of_work.things.update(thing, expected_version=expected_version):
                raise VersionConflict("Thing was updated concurrently.")

            mutation = StateMutation(
                user_id=user_id,
                thing_id=thing.id,
                run_id=run_id,
                action_id=action_id,
                mutation_type=mutation_type,
                target_type="THING",
                target_id=thing.id,
                before=before,
                after={
                    "archived_at": (
                        thing.archived_at.isoformat() if thing.archived_at is not None else None
                    ),
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
                    event_type=event_type,
                    title=title,
                    occurred_at=thing.updated_at,
                    mutation_id=mutation.id,
                )
            )
            await unit_of_work.commit()
            return MutationResultDTO(
                mutation_id=mutation.id,
                target_id=thing.id,
                target_version=thing.version,
            )
