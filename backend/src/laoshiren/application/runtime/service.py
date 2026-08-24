from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from laoshiren.application.runtime.dto import (
    MessageDTO,
    RunDTO,
    RunEventDTO,
    ThreadDTO,
    ToolExecutionClaimDTO,
)
from laoshiren.application.runtime.ports import RunDispatcher, RuntimeUnitOfWork
from laoshiren.domain.personal_state.exceptions import (
    EntityNotFound,
    InvalidStateTransition,
    VersionConflict,
)
from laoshiren.domain.runtime.entities import (
    AgentRun,
    Message,
    MessageRole,
    RunEvent,
    RunEventType,
    RunStatus,
    RunTrigger,
    Thread,
    ToolExecution,
    ToolExecutionStatus,
)

UnitOfWorkFactory = Callable[[], RuntimeUnitOfWork]


def to_thread_dto(value: Thread, *, replayed: bool = False) -> ThreadDTO:
    return ThreadDTO(
        id=value.id,
        title=value.title,
        active_thing_id=value.active_thing_id,
        archived_at=value.archived_at,
        created_at=value.created_at,
        updated_at=value.updated_at,
        replayed=replayed,
    )


def to_message_dto(value: Message) -> MessageDTO:
    return MessageDTO(
        id=value.id,
        thread_id=value.thread_id,
        role=value.role,
        content=value.content,
        run_id=value.run_id,
        source_ids=list(value.source_ids),
        metadata=dict(value.metadata),
        created_at=value.created_at,
    )


def to_run_dto(value: AgentRun, *, replayed: bool = False) -> RunDTO:
    return RunDTO(
        id=value.id,
        thread_id=value.thread_id,
        trigger=value.trigger,
        input_message_id=value.input_message_id,
        status=value.status,
        current_phase=value.current_phase,
        status_label=value.status_label,
        final_message_id=value.final_message_id,
        interrupt_id=value.interrupt_id,
        interrupt=dict(value.interrupt) if value.interrupt is not None else None,
        resume_payload=(
            dict(value.resume_payload) if value.resume_payload is not None else None
        ),
        error_code=value.error_code,
        claim_owner=value.claim_owner,
        lease_expires_at=value.lease_expires_at,
        heartbeat_at=value.heartbeat_at,
        attempt_count=value.attempt_count,
        version=value.version,
        created_at=value.created_at,
        started_at=value.started_at,
        completed_at=value.completed_at,
        updated_at=value.updated_at,
        stream_url=f"/api/v1/runs/{value.id}/events",
        replayed=replayed,
    )


def to_event_dto(value: RunEvent) -> RunEventDTO:
    return RunEventDTO(
        id=value.id,
        run_id=value.run_id,
        sequence=value.sequence,
        event=value.event_type,
        occurred_at=value.occurred_at,
        data=dict(value.data),
    )


class RuntimeApplicationService:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        run_dispatcher: RunDispatcher | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._run_dispatcher = run_dispatcher

    async def create_thread(
        self,
        *,
        user_id: UUID,
        title: str,
        idempotency_key: str,
        active_thing_id: UUID | None = None,
    ) -> ThreadDTO:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("Thread title must not be empty.")
        async with self._unit_of_work_factory() as uow:
            await uow.lock_idempotency(user_id=user_id, key=idempotency_key)
            existing = await uow.threads.get_by_idempotency(user_id=user_id, key=idempotency_key)
            if existing is not None:
                return to_thread_dto(existing, replayed=True)
            await uow.users.ensure_exists(user_id)
            if active_thing_id is not None and await uow.things.get(
                user_id=user_id, thing_id=active_thing_id
            ) is None:
                raise EntityNotFound("Thing was not found.")
            thread = Thread(
                user_id=user_id,
                title=clean_title,
                idempotency_key=idempotency_key,
                active_thing_id=active_thing_id,
            )
            await uow.threads.add(thread)
            await uow.commit()
            return to_thread_dto(thread)

    async def get_thread(self, *, user_id: UUID, thread_id: UUID) -> ThreadDTO:
        async with self._unit_of_work_factory() as uow:
            thread = await uow.threads.get(user_id=user_id, thread_id=thread_id)
            if thread is None:
                raise EntityNotFound("Thread was not found.")
            return to_thread_dto(thread)

    async def list_threads(
        self, *, user_id: UUID, limit: int = 50, include_archived: bool = False
    ) -> list[ThreadDTO]:
        async with self._unit_of_work_factory() as uow:
            values = await uow.threads.list_for_user(
                user_id=user_id, limit=limit, include_archived=include_archived
            )
            return [to_thread_dto(value) for value in values]

    async def archive_thread(self, *, user_id: UUID, thread_id: UUID) -> ThreadDTO:
        async with self._unit_of_work_factory() as uow:
            thread = await uow.threads.get(user_id=user_id, thread_id=thread_id)
            if thread is None:
                raise EntityNotFound("Thread was not found.")
            thread.archive()
            await uow.threads.archive(thread)
            await uow.commit()
            return to_thread_dto(thread)

    async def list_messages(
        self, *, user_id: UUID, thread_id: UUID, limit: int = 100
    ) -> list[MessageDTO]:
        async with self._unit_of_work_factory() as uow:
            if await uow.threads.get(user_id=user_id, thread_id=thread_id) is None:
                raise EntityNotFound("Thread was not found.")
            values = await uow.messages.list_for_thread(
                user_id=user_id, thread_id=thread_id, limit=limit
            )
            return [to_message_dto(value) for value in values]

    async def create_user_run(
        self,
        *,
        user_id: UUID,
        thread_id: UUID,
        content: str,
        source_ids: list[UUID],
        idempotency_key: str,
    ) -> RunDTO:
        clean_content = content.strip()
        if not clean_content:
            raise ValueError("Run message content must not be empty.")
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("Run source_ids must not contain duplicates.")
        async with self._unit_of_work_factory() as uow:
            await uow.lock_idempotency(user_id=user_id, key=idempotency_key)
            existing = await uow.runs.get_by_idempotency(user_id=user_id, key=idempotency_key)
            if existing is not None:
                return to_run_dto(existing, replayed=True)
            thread = await uow.threads.get(user_id=user_id, thread_id=thread_id)
            if thread is None or thread.archived_at is not None:
                raise EntityNotFound("Active Thread was not found.")
            for source_id in source_ids:
                if await uow.sources.get(user_id=user_id, source_id=source_id) is None:
                    raise EntityNotFound("Source was not found.")
            run = AgentRun(
                user_id=user_id,
                thread_id=thread_id,
                trigger=RunTrigger.USER_MESSAGE,
                idempotency_key=idempotency_key,
            )
            message = Message(
                user_id=user_id,
                thread_id=thread_id,
                role=MessageRole.USER,
                content=clean_content,
                run_id=run.id,
                source_ids=list(source_ids),
            )
            run.input_message_id = message.id
            await uow.runs.add(run)
            await uow.flush()
            await uow.messages.add(message)
            await uow.runs.append_event(
                run_id=run.id,
                event_type=RunEventType.STATUS_UPDATED,
                data={"status": RunStatus.QUEUED, "label": "等待开始", "phase": "queued"},
            )
            await uow.commit()
            result = to_run_dto(run)
        if self._run_dispatcher is not None:
            await self._run_dispatcher.dispatch(user_id=user_id, run_id=run.id)
        return result

    async def get_run(self, *, user_id: UUID, run_id: UUID) -> RunDTO:
        async with self._unit_of_work_factory() as uow:
            run = await uow.runs.get(user_id=user_id, run_id=run_id)
            if run is None:
                raise EntityNotFound("Run was not found.")
            return to_run_dto(run)

    async def recover_pending_runs(self, *, limit: int = 500) -> int:
        """Requeue crash-abandoned Runs and dispatch all durable queued work."""
        dispatches: list[tuple[UUID, UUID]] = []
        async with self._unit_of_work_factory() as uow:
            runs = await uow.runs.list_recoverable(now=datetime.now(UTC), limit=limit)
            for run in runs:
                if run.status is RunStatus.RUNNING:
                    expected_version = run.version
                    run.recover_after_crash()
                    if not await uow.runs.update(run, expected_version=expected_version):
                        continue
                    await uow.runs.append_event(
                        run_id=run.id,
                        event_type=RunEventType.STATUS_UPDATED,
                        data={
                            "status": RunStatus.QUEUED.value,
                            "phase": run.current_phase,
                            "label": run.status_label,
                            "reason": "service_restart",
                        },
                    )
                dispatches.append((run.user_id, run.id))
            await uow.commit()
        if self._run_dispatcher is not None:
            for user_id, run_id in dispatches:
                await self._run_dispatcher.dispatch(user_id=user_id, run_id=run_id)
        return len(dispatches)

    async def claim_run(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        owner: str,
        lease_seconds: float,
    ) -> RunDTO | None:
        if not owner.strip() or lease_seconds <= 0:
            raise ValueError("Run claim owner and lease must be valid.")
        now = datetime.now(UTC)
        async with self._unit_of_work_factory() as uow:
            run = await uow.runs.claim(
                user_id=user_id,
                run_id=run_id,
                owner=owner,
                now=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
            )
            if run is None:
                await uow.rollback()
                return None
            await uow.runs.append_event(
                run_id=run.id,
                event_type=RunEventType.RUN_STARTED,
                data={
                    "phase": run.current_phase,
                    "label": run.status_label,
                    "attempt": run.attempt_count,
                    "claim_owner": owner,
                },
            )
            await uow.commit()
            return to_run_dto(run)

    async def renew_run_lease(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        owner: str,
        lease_seconds: float,
    ) -> bool:
        now = datetime.now(UTC)
        async with self._unit_of_work_factory() as uow:
            renewed = await uow.runs.renew_lease(
                user_id=user_id,
                run_id=run_id,
                owner=owner,
                now=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
            )
            if renewed:
                await uow.commit()
            else:
                await uow.rollback()
            return renewed

    async def claim_tool_execution(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        action_id: str,
        tool_name: str,
        arguments_hash: str,
        owner: str,
        lease_seconds: float,
    ) -> ToolExecutionClaimDTO:
        now = datetime.now(UTC)
        execution = ToolExecution(
            run_id=run_id,
            action_id=action_id,
            tool_name=tool_name,
            arguments_hash=arguments_hash,
            status=ToolExecutionStatus.RUNNING,
            claim_owner=owner,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
        )
        async with self._unit_of_work_factory() as uow:
            run = await uow.runs.get(user_id=user_id, run_id=run_id)
            if run is None:
                raise EntityNotFound("Run was not found.")
            if run.claim_owner != owner or run.status is not RunStatus.RUNNING:
                raise InvalidStateTransition("Run is not owned by this Tool worker.")
            if await uow.tool_executions.add_if_absent(execution):
                await uow.commit()
                return ToolExecutionClaimDTO(acquired=True)
            existing = await uow.tool_executions.get(
                run_id=run_id, action_id=action_id
            )
            if existing is None:
                raise RuntimeError("Tool execution conflict points to missing data.")
            if (
                existing.tool_name != tool_name
                or existing.arguments_hash != arguments_hash
            ):
                raise InvalidStateTransition(
                    "Tool action id was reused with different arguments."
                )
            if existing.result is not None:
                await uow.rollback()
                return ToolExecutionClaimDTO(
                    acquired=False, cached_result=dict(existing.result)
                )
            acquired = await uow.tool_executions.takeover_if_expired(
                existing,
                now=now,
                owner=owner,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
            )
            if acquired:
                await uow.commit()
            else:
                await uow.rollback()
            return ToolExecutionClaimDTO(acquired=acquired)

    async def complete_tool_execution(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        action_id: str,
        owner: str,
        result: dict[str, Any],
        succeeded: bool,
    ) -> None:
        async with self._unit_of_work_factory() as uow:
            run = await uow.runs.get(user_id=user_id, run_id=run_id)
            if run is None:
                raise EntityNotFound("Run was not found.")
            if run.claim_owner != owner or run.status is not RunStatus.RUNNING:
                raise InvalidStateTransition("Run is not owned by this Tool worker.")
            completed = await uow.tool_executions.complete(
                run_id=run_id,
                action_id=action_id,
                owner=owner,
                result=result,
                succeeded=succeeded,
                now=datetime.now(UTC),
            )
            if not completed:
                raise InvalidStateTransition("Tool execution lease was lost.")
            await uow.commit()

    async def resume_run(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        interrupt_id: UUID,
        response: dict[str, Any],
        expected_version: int,
        idempotency_key: str,
    ) -> RunDTO:
        result = await self._change_run(
            user_id=user_id,
            run_id=run_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            operation="RESUME",
            interrupt_id=interrupt_id,
            response=response,
        )
        if self._run_dispatcher is not None and not result.replayed:
            await self._run_dispatcher.dispatch(user_id=user_id, run_id=run_id)
        return result

    async def cancel_run(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> RunDTO:
        return await self._change_run(
            user_id=user_id,
            run_id=run_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            operation="CANCEL",
        )

    async def _change_run(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        expected_version: int,
        idempotency_key: str,
        operation: str,
        interrupt_id: UUID | None = None,
        response: dict[str, Any] | None = None,
    ) -> RunDTO:
        async with self._unit_of_work_factory() as uow:
            await uow.lock_idempotency(user_id=user_id, key=idempotency_key)
            previous = await uow.runs.get_operation(user_id=user_id, key=idempotency_key)
            if previous is not None:
                previous_run_id, _ = previous
                run = await uow.runs.get(user_id=user_id, run_id=previous_run_id)
                if run is None:
                    raise RuntimeError("Run operation points to missing data.")
                return to_run_dto(run, replayed=True)
            run = await uow.runs.get(user_id=user_id, run_id=run_id)
            if run is None:
                raise EntityNotFound("Run was not found.")
            if run.version != expected_version:
                raise VersionConflict("Run version is stale.")
            try:
                if operation == "RESUME":
                    assert interrupt_id is not None and response is not None
                    run.resume(interrupt_id=interrupt_id, response=response)
                    event_data: dict[str, Any] = {
                        "status": RunStatus.QUEUED,
                        "label": run.status_label,
                        "phase": run.current_phase,
                    }
                else:
                    run.cancel()
                    event_data = {"status": RunStatus.CANCELLED}
            except ValueError as exception:
                raise InvalidStateTransition(str(exception)) from exception
            if not await uow.runs.update(run, expected_version=expected_version):
                raise VersionConflict("Run was updated concurrently.")
            await uow.runs.record_operation(
                user_id=user_id,
                run_id=run.id,
                key=idempotency_key,
                operation=operation,
                target_version=run.version,
            )
            await uow.runs.append_event(
                run_id=run.id,
                event_type=RunEventType.STATUS_UPDATED,
                data=event_data,
            )
            await uow.commit()
            return to_run_dto(run)

    async def list_events(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        after_event_id: UUID | None = None,
        limit: int = 200,
    ) -> list[RunEventDTO]:
        async with self._unit_of_work_factory() as uow:
            if await uow.runs.get(user_id=user_id, run_id=run_id) is None:
                raise EntityNotFound("Run was not found.")
            values = await uow.runs.list_events(
                user_id=user_id,
                run_id=run_id,
                after_event_id=after_event_id,
                limit=limit,
            )
            return [to_event_dto(value) for value in values]

    async def start_run(
        self, *, user_id: UUID, run_id: UUID, phase: str, label: str
    ) -> RunDTO:
        return await self._worker_transition(
            user_id=user_id, run_id=run_id, action="START", phase=phase, label=label
        )

    async def require_input(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        payload: dict[str, Any],
        claim_owner: str | None = None,
    ) -> RunDTO:
        return await self._worker_transition(
            user_id=user_id,
            run_id=run_id,
            action="WAIT",
            payload=payload,
            claim_owner=claim_owner,
        )

    async def complete_run(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        content: str,
        claim_owner: str | None = None,
    ) -> RunDTO:
        return await self._worker_transition(
            user_id=user_id,
            run_id=run_id,
            action="COMPLETE",
            content=content,
            claim_owner=claim_owner,
        )

    async def fail_run(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        error_code: str,
        claim_owner: str | None = None,
    ) -> RunDTO:
        return await self._worker_transition(
            user_id=user_id,
            run_id=run_id,
            action="FAIL",
            error_code=error_code,
            claim_owner=claim_owner,
        )

    async def emit_event(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        event_type: RunEventType,
        data: dict[str, Any],
    ) -> RunEventDTO:
        async with self._unit_of_work_factory() as uow:
            if await uow.runs.get(user_id=user_id, run_id=run_id) is None:
                raise EntityNotFound("Run was not found.")
            event = await uow.runs.append_event(
                run_id=run_id, event_type=event_type, data=data
            )
            await uow.commit()
            return to_event_dto(event)

    async def _worker_transition(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        action: str,
        phase: str | None = None,
        label: str | None = None,
        payload: dict[str, Any] | None = None,
        content: str | None = None,
        error_code: str | None = None,
        claim_owner: str | None = None,
    ) -> RunDTO:
        async with self._unit_of_work_factory() as uow:
            run = await uow.runs.get(user_id=user_id, run_id=run_id)
            if run is None:
                raise EntityNotFound("Run was not found.")
            if claim_owner is not None and run.claim_owner != claim_owner:
                raise InvalidStateTransition("Run lease is no longer owned by this worker.")
            expected_version = run.version
            try:
                if action == "START":
                    run.start(phase=phase, label=label)
                    event_type = RunEventType.RUN_STARTED
                    data: dict[str, Any] = {"phase": phase, "label": label}
                elif action == "WAIT":
                    assert payload is not None
                    interrupt_id = uuid4()
                    run.wait_for_user(interrupt_id=interrupt_id, payload=payload)
                    event_type = RunEventType.INTERRUPT_REQUIRED
                    data = {"interrupt_id": str(interrupt_id), **payload}
                elif action == "COMPLETE":
                    if content is None or not content.strip():
                        raise ValueError("Assistant message must not be empty.")
                    message = Message(
                        user_id=user_id,
                        thread_id=run.thread_id,
                        role=MessageRole.ASSISTANT,
                        content=content.strip(),
                        run_id=run.id,
                    )
                    await uow.messages.add(message)
                    run.complete(final_message_id=message.id)
                    event_type = RunEventType.RUN_COMPLETED
                    data = {"message_id": str(message.id)}
                else:
                    assert error_code is not None
                    run.fail(error_code=error_code)
                    event_type = RunEventType.RUN_FAILED
                    data = {"error_code": error_code}
            except ValueError as exception:
                raise InvalidStateTransition(str(exception)) from exception
            if not await uow.runs.update(run, expected_version=expected_version):
                raise VersionConflict("Run was updated concurrently.")
            if action == "COMPLETE":
                await uow.runs.append_event(
                    run_id=run.id,
                    event_type=RunEventType.ASSISTANT_MESSAGE,
                    data={"message_id": data["message_id"], "content": content},
                )
            await uow.runs.append_event(run_id=run.id, event_type=event_type, data=data)
            await uow.commit()
            return to_run_dto(run)
