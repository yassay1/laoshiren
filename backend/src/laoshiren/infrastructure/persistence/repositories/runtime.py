from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from laoshiren.domain.runtime.entities import (
    AgentRun,
    Message,
    RunEvent,
    RunEventType,
    Thread,
)
from laoshiren.infrastructure.persistence.orm.personal_state import (
    AgentRunORM,
    MessageORM,
    RunEventORM,
    RunOperationORM,
    ThreadORM,
)


def thread_to_domain(model: ThreadORM) -> Thread:
    return Thread(
        id=model.id,
        user_id=model.user_id,
        title=model.title,
        active_thing_id=model.active_thing_id,
        idempotency_key=model.idempotency_key,
        archived_at=model.archived_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def message_to_domain(model: MessageORM) -> Message:
    return Message(
        id=model.id,
        user_id=model.user_id,
        thread_id=model.thread_id,
        role=model.role,
        content=model.content,
        run_id=model.run_id,
        source_ids=list(model.source_ids),
        metadata=dict(model.metadata_),
        created_at=model.created_at,
    )


def run_to_domain(model: AgentRunORM) -> AgentRun:
    return AgentRun(
        id=model.id,
        user_id=model.user_id,
        thread_id=model.thread_id,
        trigger=model.trigger,
        input_message_id=model.input_message_id,
        status=model.status,
        current_phase=model.current_phase,
        status_label=model.status_label,
        final_message_id=model.final_message_id,
        interrupt_id=model.interrupt_id,
        interrupt=dict(model.interrupt) if model.interrupt is not None else None,
        resume_payload=(
            dict(model.resume_payload) if model.resume_payload is not None else None
        ),
        error_code=model.error_code,
        version=model.version,
        event_sequence=model.event_sequence,
        idempotency_key=model.idempotency_key,
        created_at=model.created_at,
        started_at=model.started_at,
        completed_at=model.completed_at,
        updated_at=model.updated_at,
    )


def event_to_domain(model: RunEventORM) -> RunEvent:
    return RunEvent(
        id=model.id,
        run_id=model.run_id,
        sequence=model.sequence,
        event_type=model.event_type,
        data=dict(model.data),
        occurred_at=model.occurred_at,
    )


class SqlAlchemyThreadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, thread: Thread) -> None:
        self._session.add(
            ThreadORM(
                id=thread.id,
                user_id=thread.user_id,
                title=thread.title,
                active_thing_id=thread.active_thing_id,
                idempotency_key=thread.idempotency_key,
                archived_at=thread.archived_at,
                created_at=thread.created_at,
                updated_at=thread.updated_at,
            )
        )

    async def get(self, *, user_id: UUID, thread_id: UUID) -> Thread | None:
        model = await self._session.scalar(
            select(ThreadORM).where(ThreadORM.id == thread_id, ThreadORM.user_id == user_id)
        )
        return thread_to_domain(model) if model is not None else None

    async def get_by_idempotency(self, *, user_id: UUID, key: str) -> Thread | None:
        model = await self._session.scalar(
            select(ThreadORM).where(
                ThreadORM.user_id == user_id, ThreadORM.idempotency_key == key
            )
        )
        return thread_to_domain(model) if model is not None else None

    async def list_for_user(
        self, *, user_id: UUID, limit: int, include_archived: bool
    ) -> list[Thread]:
        statement = select(ThreadORM).where(ThreadORM.user_id == user_id)
        if not include_archived:
            statement = statement.where(ThreadORM.archived_at.is_(None))
        models = (
            await self._session.scalars(
                statement.order_by(ThreadORM.updated_at.desc(), ThreadORM.id.desc()).limit(limit)
            )
        ).all()
        return [thread_to_domain(model) for model in models]

    async def archive(self, thread: Thread) -> None:
        await self._session.execute(
            update(ThreadORM)
            .where(ThreadORM.id == thread.id, ThreadORM.user_id == thread.user_id)
            .values(archived_at=thread.archived_at, updated_at=thread.updated_at)
        )


class SqlAlchemyMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, message: Message) -> None:
        self._session.add(
            MessageORM(
                id=message.id,
                user_id=message.user_id,
                thread_id=message.thread_id,
                role=message.role,
                content=message.content,
                run_id=message.run_id,
                source_ids=message.source_ids,
                metadata_=message.metadata,
                created_at=message.created_at,
            )
        )

    async def get(self, *, user_id: UUID, message_id: UUID) -> Message | None:
        model = await self._session.scalar(
            select(MessageORM).where(MessageORM.id == message_id, MessageORM.user_id == user_id)
        )
        return message_to_domain(model) if model is not None else None

    async def list_for_thread(
        self, *, user_id: UUID, thread_id: UUID, limit: int
    ) -> list[Message]:
        models = (
            await self._session.scalars(
                select(MessageORM)
                .where(MessageORM.user_id == user_id, MessageORM.thread_id == thread_id)
                .order_by(MessageORM.created_at, MessageORM.id)
                .limit(limit)
            )
        ).all()
        return [message_to_domain(model) for model in models]


class SqlAlchemyRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, run: AgentRun) -> None:
        self._session.add(
            AgentRunORM(
                id=run.id,
                user_id=run.user_id,
                thread_id=run.thread_id,
                trigger=run.trigger,
                input_message_id=run.input_message_id,
                status=run.status,
                current_phase=run.current_phase,
                status_label=run.status_label,
                final_message_id=run.final_message_id,
                interrupt_id=run.interrupt_id,
                interrupt=run.interrupt,
                resume_payload=run.resume_payload,
                error_code=run.error_code,
                version=run.version,
                event_sequence=run.event_sequence,
                idempotency_key=run.idempotency_key,
                created_at=run.created_at,
                started_at=run.started_at,
                completed_at=run.completed_at,
                updated_at=run.updated_at,
            )
        )

    async def get(self, *, user_id: UUID, run_id: UUID) -> AgentRun | None:
        model = await self._session.scalar(
            select(AgentRunORM).where(
                AgentRunORM.id == run_id, AgentRunORM.user_id == user_id
            )
        )
        return run_to_domain(model) if model is not None else None

    async def get_by_idempotency(self, *, user_id: UUID, key: str) -> AgentRun | None:
        model = await self._session.scalar(
            select(AgentRunORM).where(
                AgentRunORM.user_id == user_id, AgentRunORM.idempotency_key == key
            )
        )
        return run_to_domain(model) if model is not None else None

    async def update(self, run: AgentRun, *, expected_version: int) -> bool:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(AgentRunORM)
                .where(AgentRunORM.id == run.id, AgentRunORM.version == expected_version)
                .values(
                    status=run.status,
                    current_phase=run.current_phase,
                    status_label=run.status_label,
                    final_message_id=run.final_message_id,
                    interrupt_id=run.interrupt_id,
                    interrupt=run.interrupt,
                    resume_payload=run.resume_payload,
                    error_code=run.error_code,
                    version=run.version,
                    started_at=run.started_at,
                    completed_at=run.completed_at,
                    updated_at=run.updated_at,
                )
            ),
        )
        return result.rowcount == 1

    async def get_operation(self, *, user_id: UUID, key: str) -> tuple[UUID, int] | None:
        row = (
            await self._session.execute(
                select(RunOperationORM.run_id, RunOperationORM.target_version).where(
                    RunOperationORM.user_id == user_id,
                    RunOperationORM.idempotency_key == key,
                )
            )
        ).one_or_none()
        return (row[0], row[1]) if row is not None else None

    async def record_operation(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        key: str,
        operation: str,
        target_version: int,
    ) -> None:
        self._session.add(
            RunOperationORM(
                user_id=user_id,
                run_id=run_id,
                idempotency_key=key,
                operation=operation,
                target_version=target_version,
            )
        )

    async def append_event(
        self, *, run_id: UUID, event_type: RunEventType, data: dict[str, Any]
    ) -> RunEvent:
        sequence = await self._session.scalar(
            update(AgentRunORM)
            .where(AgentRunORM.id == run_id)
            .values(event_sequence=AgentRunORM.event_sequence + 1)
            .returning(AgentRunORM.event_sequence)
        )
        if sequence is None:
            raise RuntimeError("Cannot append an event to a missing Run.")
        event = RunEvent(
            run_id=run_id,
            sequence=sequence,
            event_type=event_type,
            data=data,
        )
        self._session.add(
            RunEventORM(
                id=event.id,
                run_id=event.run_id,
                sequence=event.sequence,
                event_type=event.event_type,
                data=event.data,
                occurred_at=event.occurred_at,
            )
        )
        return event

    async def list_events(
        self, *, user_id: UUID, run_id: UUID, after_event_id: UUID | None, limit: int
    ) -> list[RunEvent]:
        statement = (
            select(RunEventORM)
            .join(AgentRunORM, AgentRunORM.id == RunEventORM.run_id)
            .where(AgentRunORM.user_id == user_id, RunEventORM.run_id == run_id)
        )
        if after_event_id is not None:
            sequence = await self._session.scalar(
                select(RunEventORM.sequence).where(
                    RunEventORM.id == after_event_id, RunEventORM.run_id == run_id
                )
            )
            if sequence is None:
                return []
            statement = statement.where(RunEventORM.sequence > sequence)
        models = (
            await self._session.scalars(statement.order_by(RunEventORM.sequence).limit(limit))
        ).all()
        return [event_to_domain(model) for model in models]
