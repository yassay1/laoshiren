from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from laoshiren.domain.runtime.entities import (
    AgentRun,
    Message,
    RunEvent,
    RunEventType,
    RunStatus,
    Thread,
    ToolExecution,
    ToolExecutionStatus,
)
from laoshiren.infrastructure.persistence.orm.personal_state import (
    AgentRunORM,
    MessageORM,
    RunEventORM,
    RunOperationORM,
    ThreadORM,
    ToolExecutionORM,
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
        claim_owner=model.claim_owner,
        claim_token=model.claim_token,
        lease_expires_at=model.lease_expires_at,
        heartbeat_at=model.heartbeat_at,
        attempt_count=model.attempt_count,
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
        models = list(
            await self._session.scalars(
                select(MessageORM)
                .where(MessageORM.user_id == user_id, MessageORM.thread_id == thread_id)
                .order_by(MessageORM.created_at.desc(), MessageORM.id.desc())
                .limit(limit)
            )
        )
        models.reverse()
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
                claim_owner=run.claim_owner,
                claim_token=run.claim_token,
                lease_expires_at=run.lease_expires_at,
                heartbeat_at=run.heartbeat_at,
                attempt_count=run.attempt_count,
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

    async def list_recoverable(self, *, now: datetime, limit: int) -> list[AgentRun]:
        models = (
            await self._session.scalars(
                select(AgentRunORM)
                .where(
                    or_(
                        AgentRunORM.status == RunStatus.QUEUED,
                        (
                            (AgentRunORM.status == RunStatus.RUNNING)
                            & (
                                AgentRunORM.lease_expires_at.is_(None)
                                | (AgentRunORM.lease_expires_at <= now)
                            )
                        ),
                    )
                )
                .order_by(AgentRunORM.created_at, AgentRunORM.id)
                .limit(limit)
            )
        ).all()
        return [run_to_domain(model) for model in models]

    async def claim(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        owner: str,
        claim_token: UUID,
        now: datetime,
        lease_expires_at: datetime,
    ) -> AgentRun | None:
        claimed = await self._session.scalar(
            update(AgentRunORM)
            .where(
                AgentRunORM.id == run_id,
                AgentRunORM.user_id == user_id,
                or_(
                    AgentRunORM.status == RunStatus.QUEUED,
                    (
                        (AgentRunORM.status == RunStatus.RUNNING)
                        & (
                            AgentRunORM.lease_expires_at.is_(None)
                            | (AgentRunORM.lease_expires_at <= now)
                        )
                    ),
                ),
            )
            .values(
                status=RunStatus.RUNNING,
                current_phase="executive",
                status_label="正在理解并处理",
                claim_owner=owner,
                claim_token=claim_token,
                heartbeat_at=now,
                lease_expires_at=lease_expires_at,
                attempt_count=AgentRunORM.attempt_count + 1,
                started_at=func.coalesce(AgentRunORM.started_at, now),
                updated_at=now,
                version=AgentRunORM.version + 1,
            )
            .returning(AgentRunORM.id)
        )
        if claimed is None:
            return None
        model = await self._session.scalar(select(AgentRunORM).where(AgentRunORM.id == claimed))
        return run_to_domain(model) if model is not None else None

    async def renew_lease(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        owner: str,
        claim_token: UUID,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(AgentRunORM)
                .where(
                    AgentRunORM.id == run_id,
                    AgentRunORM.user_id == user_id,
                    AgentRunORM.status == RunStatus.RUNNING,
                    AgentRunORM.claim_owner == owner,
                    AgentRunORM.claim_token == claim_token,
                )
                .values(heartbeat_at=now, lease_expires_at=lease_expires_at, updated_at=now)
            ),
        )
        return result.rowcount == 1

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
                    claim_owner=run.claim_owner,
                    claim_token=run.claim_token,
                    lease_expires_at=run.lease_expires_at,
                    heartbeat_at=run.heartbeat_at,
                    attempt_count=run.attempt_count,
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


def tool_execution_to_domain(model: ToolExecutionORM) -> ToolExecution:
    return ToolExecution(
        id=model.id,
        run_id=model.run_id,
        action_id=model.action_id,
        tool_name=model.tool_name,
        arguments_hash=model.arguments_hash,
        status=model.status,
        result=dict(model.result) if model.result is not None else None,
        claim_owner=model.claim_owner,
        claim_token=model.claim_token,
        lease_expires_at=model.lease_expires_at,
        replay_safe=model.replay_safe,
        idempotency_key=model.idempotency_key,
        attempt_count=model.attempt_count,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlAlchemyToolExecutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, *, run_id: UUID, action_id: str) -> ToolExecution | None:
        model = await self._session.scalar(
            select(ToolExecutionORM).where(
                ToolExecutionORM.run_id == run_id,
                ToolExecutionORM.action_id == action_id,
            )
        )
        return tool_execution_to_domain(model) if model is not None else None

    async def add_if_absent(self, execution: ToolExecution) -> bool:
        inserted = await self._session.scalar(
            insert(ToolExecutionORM)
            .values(
                id=execution.id,
                run_id=execution.run_id,
                action_id=execution.action_id,
                tool_name=execution.tool_name,
                arguments_hash=execution.arguments_hash,
                status=execution.status,
                result=execution.result,
                claim_owner=execution.claim_owner,
                claim_token=execution.claim_token,
                lease_expires_at=execution.lease_expires_at,
                replay_safe=execution.replay_safe,
                idempotency_key=execution.idempotency_key,
                attempt_count=execution.attempt_count,
                created_at=execution.created_at,
                updated_at=execution.updated_at,
            )
            .on_conflict_do_nothing(index_elements=["run_id", "action_id"])
            .returning(ToolExecutionORM.id)
        )
        return inserted is not None

    async def takeover_if_expired(
        self,
        execution: ToolExecution,
        *,
        now: datetime,
        owner: str,
        claim_token: UUID,
        lease_expires_at: datetime,
    ) -> bool:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(ToolExecutionORM)
                .where(
                    ToolExecutionORM.id == execution.id,
                    ToolExecutionORM.status == ToolExecutionStatus.RUNNING,
                    ToolExecutionORM.lease_expires_at <= now,
                )
                .values(
                    claim_owner=owner,
                    claim_token=claim_token,
                    lease_expires_at=lease_expires_at,
                    attempt_count=ToolExecutionORM.attempt_count + 1,
                    updated_at=now,
                )
            ),
        )
        return result.rowcount == 1

    async def complete(
        self,
        *,
        run_id: UUID,
        action_id: str,
        owner: str,
        claim_token: UUID,
        result: dict[str, Any],
        succeeded: bool,
        now: datetime,
    ) -> bool:
        updated = cast(
            CursorResult[Any],
            await self._session.execute(
                update(ToolExecutionORM)
                .where(
                    ToolExecutionORM.run_id == run_id,
                    ToolExecutionORM.action_id == action_id,
                    ToolExecutionORM.status == ToolExecutionStatus.RUNNING,
                    ToolExecutionORM.claim_owner == owner,
                    ToolExecutionORM.claim_token == claim_token,
                )
                .values(
                    status=(
                        ToolExecutionStatus.SUCCEEDED
                        if succeeded
                        else ToolExecutionStatus.FAILED
                    ),
                    result=result,
                    updated_at=now,
                )
            ),
        )
        return updated.rowcount == 1

    async def mark_unknown_if_expired(
        self, *, execution_id: UUID, now: datetime
    ) -> bool:
        updated = cast(
            CursorResult[Any],
            await self._session.execute(
                update(ToolExecutionORM)
                .where(
                    ToolExecutionORM.id == execution_id,
                    ToolExecutionORM.status == ToolExecutionStatus.RUNNING,
                    ToolExecutionORM.lease_expires_at <= now,
                    ToolExecutionORM.replay_safe.is_(False),
                )
                .values(status=ToolExecutionStatus.UNKNOWN, updated_at=now)
            ),
        )
        return updated.rowcount == 1
