from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from laoshiren.application.personal_state.ports import PersonalStateUnitOfWork
from laoshiren.application.personal_state.write_ops import WriteOutcome
from laoshiren.application.runtime.dto import (
    DurableJobClaimDTO,
    EphemeralFrameDTO,
    MessageDTO,
    RunDTO,
    RunEventDTO,
    ThreadDTO,
    ToolExecutionClaimDTO,
)
from laoshiren.application.runtime.durable_job_claim import claim_ready_jobs
from laoshiren.application.runtime.ports import (
    RunDispatcher,
    RuntimeLiveSubscription,
    RuntimeUnitOfWork,
    RuntimeWakeup,
)
from laoshiren.application.runtime.receipts import build_tool_receipt
from laoshiren.domain.personal_state.exceptions import (
    EntityNotFound,
    InvalidStateTransition,
    VersionConflict,
)
from laoshiren.domain.runtime.entities import (
    TERMINAL_RUN_STATUSES,
    AgentRun,
    DurableJob,
    DurableJobKind,
    DurableJobStatus,
    Message,
    MessageRole,
    RunEvent,
    RunEventType,
    RunInteraction,
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
        resume_payload=(dict(value.resume_payload) if value.resume_payload is not None else None),
        error_code=value.error_code,
        claim_owner=value.claim_owner,
        claim_token=value.claim_token,
        lease_expires_at=value.lease_expires_at,
        heartbeat_at=value.heartbeat_at,
        attempt_count=value.attempt_count,
        version=value.version,
        last_event_sequence=value.event_sequence,
        pending_interaction=(
            {
                "interaction_id": str(value.interrupt_id),
                "type": value.interrupt.get("type", "CONFIRMATION"),
                "action_id": value.interrupt.get("action_id"),
                "request": dict(value.interrupt),
            }
            if value.interrupt_id is not None and value.interrupt is not None
            else None
        ),
        active_time_used_ms=value.active_time_used_ms,
        active_started_at=value.active_started_at,
        terminal_output=(
            dict(value.terminal_output) if value.terminal_output is not None else None
        ),
        graph_terminal_at=value.graph_terminal_at,
        budget_snapshot=dict(value.budget_snapshot),
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
        visibility=value.visibility,
        schema_version=value.schema_version,
    )


class RuntimeApplicationService:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        run_dispatcher: RunDispatcher | None = None,
        wakeup: RuntimeWakeup | None = None,
        budget_snapshot: dict[str, Any] | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._run_dispatcher = run_dispatcher
        self._wakeup = wakeup
        self._budget_snapshot = dict(budget_snapshot or {})

    async def publish_wakeup(self, *, run_id: UUID, latest_sequence: int) -> None:
        if self._wakeup is not None:
            await self._wakeup.publish(run_id=run_id, latest_sequence=latest_sequence)

    async def wait_for_wakeup(
        self, *, run_id: UUID, timeout_seconds: float
    ) -> EphemeralFrameDTO | None:
        if self._wakeup is None:
            return None
        return await self._wakeup.wait(run_id=run_id, timeout_seconds=timeout_seconds)

    async def subscribe_to_live_frames(self, *, run_id: UUID) -> RuntimeLiveSubscription | None:
        if self._wakeup is None:
            return None
        return await self._wakeup.subscribe(run_id=run_id)

    async def emit_ephemeral_frame(
        self, *, user_id: UUID, run_id: UUID, frame_type: str, data: dict[str, Any]
    ) -> None:
        if frame_type not in {"assistant.delta", "stream.reset"}:
            raise ValueError("Unsupported ephemeral frame type.")
        async with self._unit_of_work_factory() as uow:
            if await uow.runs.get(user_id=user_id, run_id=run_id) is None:
                raise EntityNotFound("Run was not found.")
        if self._wakeup is not None:
            await self._wakeup.publish_frame(
                EphemeralFrameDTO(run_id=run_id, frame_type=frame_type, data=dict(data))
            )

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
            if (
                active_thing_id is not None
                and await uow.things.get(user_id=user_id, thing_id=active_thing_id) is None
            ):
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
                budget_snapshot=dict(self._budget_snapshot),
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
                event_type=RunEventType.RUN_QUEUED,
                data={"status": RunStatus.QUEUED, "label": "等待开始", "phase": "queued"},
            )
            await uow.durable_jobs.add(
                DurableJob(
                    user_id=user_id,
                    kind=DurableJobKind.AGENT_RUN,
                    dedupe_key=f"agent-run:{run.id}",
                    payload={"run_id": str(run.id)},
                )
            )
            await uow.commit()
            result = to_run_dto(run)
        if self._run_dispatcher is not None:
            await self._run_dispatcher.dispatch(user_id=user_id, run_id=run.id)
        return result

    async def create_automation_run(
        self,
        *,
        user_id: UUID,
        automation_id: UUID,
        thing_id: UUID | None,
        title: str,
        message: str,
        occurrence_key: str,
    ) -> RunDTO:
        clean_title = title.strip()
        clean_message = message.strip()
        if not clean_title or not clean_message:
            raise ValueError("Automation run title and message must not be empty.")
        if not occurrence_key.strip():
            raise ValueError("Automation occurrence_key must not be empty.")
        thread_key = f"automation-inbox:{user_id}"
        run_key = f"automation-run:{occurrence_key}"
        content = f"[自动化提醒] {clean_title}\n{clean_message}"
        async with self._unit_of_work_factory() as uow:
            await uow.lock_idempotency(user_id=user_id, key=run_key)
            existing = await uow.runs.get_by_idempotency(user_id=user_id, key=run_key)
            if existing is not None:
                return to_run_dto(existing, replayed=True)
            thread = await uow.threads.get_by_idempotency(user_id=user_id, key=thread_key)
            if thread is None:
                await uow.users.ensure_exists(user_id)
                thread = Thread(
                    user_id=user_id,
                    title="自动化",
                    idempotency_key=thread_key,
                    active_thing_id=thing_id,
                )
                await uow.threads.add(thread)
                await uow.flush()
            elif thing_id is not None:
                thread.active_thing_id = thing_id
            run = AgentRun(
                user_id=user_id,
                thread_id=thread.id,
                trigger=RunTrigger.AUTOMATION,
                idempotency_key=run_key,
                budget_snapshot=dict(self._budget_snapshot),
            )
            input_message = Message(
                user_id=user_id,
                thread_id=thread.id,
                role=MessageRole.SYSTEM_EVENT,
                content=content,
                run_id=run.id,
                metadata={
                    "automation_id": str(automation_id),
                    "occurrence_key": occurrence_key,
                    "thing_id": str(thing_id) if thing_id is not None else None,
                },
            )
            run.input_message_id = input_message.id
            await uow.runs.add(run)
            await uow.flush()
            await uow.messages.add(input_message)
            await uow.runs.append_event(
                run_id=run.id,
                event_type=RunEventType.RUN_QUEUED,
                data={
                    "status": RunStatus.QUEUED.value,
                    "label": "自动化触发",
                    "phase": "automation",
                    "automation_id": str(automation_id),
                },
            )
            await uow.durable_jobs.add(
                DurableJob(
                    user_id=user_id,
                    kind=DurableJobKind.AGENT_RUN,
                    dedupe_key=f"agent-run:{run.id}",
                    payload={"run_id": str(run.id)},
                )
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

    async def claim_agent_run_jobs(
        self, *, owner: str, lease_seconds: float, limit: int
    ) -> list[DurableJobClaimDTO]:
        if not owner.strip() or lease_seconds <= 0 or limit <= 0:
            raise ValueError("Durable Job claim parameters must be positive.")
        now = datetime.now(UTC)
        async with self._unit_of_work_factory() as uow:
            jobs = await claim_ready_jobs(
                uow,
                kind=DurableJobKind.AGENT_RUN,
                owner=owner,
                now=now,
                lease_until=now + timedelta(seconds=lease_seconds),
                limit=limit,
            )
            claims: list[DurableJobClaimDTO] = []
            for job in jobs:
                run_id = UUID(str(job.payload["run_id"]))
                claims.append(
                    DurableJobClaimDTO(
                        job_id=job.id,
                        user_id=job.user_id,
                        run_id=run_id,
                        claim_epoch=job.claim_epoch,
                    )
                )
            await uow.commit()
            return claims

    async def settle_agent_run_job(
        self,
        *,
        claim: DurableJobClaimDTO,
        owner: str,
        error_code: str | None = None,
    ) -> None:
        async with self._unit_of_work_factory() as uow:
            run = await uow.runs.get(user_id=claim.user_id, run_id=claim.run_id)
            if run is None:
                status = DurableJobStatus.FAILED
                error_code = "RUN_NOT_FOUND"
            elif run.status is RunStatus.WAITING_FOR_USER:
                status = DurableJobStatus.PAUSED
            elif run.status is RunStatus.CANCELLED:
                status = DurableJobStatus.CANCELLED
            elif run.status in TERMINAL_RUN_STATUSES:
                status = DurableJobStatus.COMPLETED
            else:
                status = DurableJobStatus.READY
            if status is DurableJobStatus.READY:
                raise InvalidStateTransition("Agent Run returned without settling its state.")
            settled = await uow.durable_jobs.settle(
                job_id=claim.job_id,
                owner=owner,
                claim_epoch=claim.claim_epoch,
                status=status,
                now=datetime.now(UTC),
                error_code=error_code,
            )
            if not settled:
                raise InvalidStateTransition("Durable Job fencing token was lost.")
            await uow.commit()

    async def renew_agent_run_job(
        self,
        *,
        claim: DurableJobClaimDTO,
        owner: str,
        lease_seconds: float,
    ) -> bool:
        now = datetime.now(UTC)
        async with self._unit_of_work_factory() as uow:
            renewed = await uow.durable_jobs.renew(
                job_id=claim.job_id,
                owner=owner,
                claim_epoch=claim.claim_epoch,
                lease_until=now + timedelta(seconds=lease_seconds),
                now=now,
            )
            if renewed:
                await uow.commit()
            else:
                await uow.rollback()
            return renewed

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
                        event_type=RunEventType.RUN_QUEUED,
                        data={
                            "status": RunStatus.QUEUED.value,
                            "phase": run.current_phase,
                            "label": run.status_label,
                            "reason": "lease_expired",
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
        claim_token = uuid4()
        async with self._unit_of_work_factory() as uow:
            run = await uow.runs.claim(
                user_id=user_id,
                run_id=run_id,
                owner=owner,
                claim_token=claim_token,
                now=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
            )
            if run is None:
                await uow.rollback()
                return None
            event = await uow.runs.append_event(
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
            result = to_run_dto(run)
        await self.publish_wakeup(run_id=run_id, latest_sequence=event.sequence)
        return result

    async def renew_run_lease(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        owner: str,
        claim_token: UUID,
        lease_seconds: float,
    ) -> bool:
        now = datetime.now(UTC)
        async with self._unit_of_work_factory() as uow:
            renewed = await uow.runs.renew_lease(
                user_id=user_id,
                run_id=run_id,
                owner=owner,
                claim_token=claim_token,
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
        run_claim_token: UUID,
        replay_safe: bool = True,
        idempotency_key: str | None = None,
    ) -> ToolExecutionClaimDTO:
        now = datetime.now(UTC)
        claim_token = uuid4()
        execution = ToolExecution(
            run_id=run_id,
            action_id=action_id,
            tool_name=tool_name,
            arguments_hash=arguments_hash,
            status=ToolExecutionStatus.IN_PROGRESS,
            claim_owner=owner,
            claim_token=claim_token,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            replay_safe=replay_safe,
            idempotency_key=idempotency_key,
        )
        async with self._unit_of_work_factory() as uow:
            run = await uow.runs.get(user_id=user_id, run_id=run_id)
            if run is None:
                raise EntityNotFound("Run was not found.")
            if (
                run.claim_owner != owner
                or run.claim_token != run_claim_token
                or run.status is not RunStatus.RUNNING
            ):
                raise InvalidStateTransition("Run is not owned by this Tool worker.")
            if await uow.tool_executions.add_if_absent(execution):
                await uow.commit()
                return ToolExecutionClaimDTO(acquired=True, claim_token=claim_token)
            existing = await uow.tool_executions.get(run_id=run_id, action_id=action_id)
            if existing is None:
                raise RuntimeError("Tool execution conflict points to missing data.")
            if existing.tool_name != tool_name or existing.arguments_hash != arguments_hash:
                raise InvalidStateTransition("Tool action id was reused with different arguments.")
            if existing.replay_safe != replay_safe or (
                existing.idempotency_key is not None and existing.idempotency_key != idempotency_key
            ):
                raise InvalidStateTransition(
                    "Tool action id was reused with a different replay contract."
                )
            if existing.result is not None:
                await uow.rollback()
                return ToolExecutionClaimDTO(acquired=False, cached_result=dict(existing.result))
            if existing.lease_expires_at <= now and not existing.replay_safe:
                marked_unknown = await uow.tool_executions.mark_unknown_if_expired(
                    execution_id=existing.id, now=now
                )
                if marked_unknown:
                    await uow.commit()
                else:
                    await uow.rollback()
                return ToolExecutionClaimDTO(
                    acquired=False,
                    blocked_reason=(
                        "Non-replayable Tool outcome is unknown for "
                        f"idempotency key {idempotency_key or action_id}."
                    ),
                )
            acquired = await uow.tool_executions.takeover_if_expired(
                existing,
                now=now,
                owner=owner,
                claim_token=claim_token,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
            )
            if acquired:
                await uow.commit()
            else:
                await uow.rollback()
            return ToolExecutionClaimDTO(
                acquired=acquired,
                claim_token=claim_token if acquired else None,
            )

    async def complete_tool_execution(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        action_id: str,
        owner: str,
        claim_token: UUID,
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
                claim_token=claim_token,
                result=result,
                succeeded=succeeded,
                now=datetime.now(UTC),
            )
            if not completed:
                raise InvalidStateTransition("Tool execution lease was lost.")
            await uow.commit()

    async def complete_personal_state_mutation_tool(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        action_id: str,
        owner: str,
        claim_token: UUID,
        tool_name: str,
        apply_mutation: Callable[[PersonalStateUnitOfWork], Awaitable[WriteOutcome]],
    ) -> dict[str, Any]:
        """Atomically persist a Personal State mutation and its Tool ledger receipt."""
        async with self._unit_of_work_factory() as uow:
            run = await uow.runs.get(user_id=user_id, run_id=run_id)
            if run is None:
                raise EntityNotFound("Run was not found.")
            if run.claim_owner != owner or run.status is not RunStatus.RUNNING:
                raise InvalidStateTransition("Run is not owned by this Tool worker.")
            personal_state_uow = cast(PersonalStateUnitOfWork, uow)
            outcome = await apply_mutation(personal_state_uow)
            receipt = build_tool_receipt(
                tool_name=tool_name,
                status="SUCCESS",
                code=outcome.code,
                message=outcome.message,
                data=outcome.data,
                mutation_refs=outcome.mutation_refs,
            )
            completed = await uow.tool_executions.complete(
                run_id=run_id,
                action_id=action_id,
                owner=owner,
                claim_token=claim_token,
                result=receipt,
                succeeded=True,
                now=datetime.now(UTC),
            )
            if not completed:
                raise InvalidStateTransition("Tool execution lease was lost.")
            await uow.commit()
            return outcome.data

    async def complete_mutation_tool(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        action_id: str,
        owner: str,
        claim_token: UUID,
        tool_name: str,
        apply_mutation: Callable[[PersonalStateUnitOfWork], Awaitable[WriteOutcome]],
    ) -> dict[str, Any]:
        """Atomically persist a domain mutation and its Tool ledger receipt."""
        return await self.complete_personal_state_mutation_tool(
            user_id=user_id,
            run_id=run_id,
            action_id=action_id,
            owner=owner,
            claim_token=claim_token,
            tool_name=tool_name,
            apply_mutation=apply_mutation,
        )

    async def archive_thing_and_complete_tool_execution(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        action_id: str,
        owner: str,
        claim_token: UUID,
        thing_id: UUID,
        expected_version: int,
        idempotency_key: str,
        reason: str,
    ) -> dict[str, Any]:
        from laoshiren.application.personal_state import write_ops

        return await self.complete_personal_state_mutation_tool(
            user_id=user_id,
            run_id=run_id,
            action_id=action_id,
            owner=owner,
            claim_token=claim_token,
            tool_name="thing_change_state",
            apply_mutation=lambda uow: write_ops.apply_change_archive(
                uow,
                user_id=user_id,
                thing_id=thing_id,
                expected_version=expected_version,
                action_id=action_id,
                idempotency_key=idempotency_key,
                reason=reason,
                run_id=run_id,
                archive=True,
            ),
        )

    async def reconcile_unknown_tool_execution(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        action_id: str,
        result: dict[str, Any],
        succeeded: bool,
        provider_request_id: str | None = None,
    ) -> None:
        """Record an explicit external observation; never blindly retries."""
        async with self._unit_of_work_factory() as uow:
            run = await uow.runs.get(user_id=user_id, run_id=run_id)
            if run is None:
                raise EntityNotFound("Run was not found.")
            execution = await uow.tool_executions.get(run_id=run_id, action_id=action_id)
            if execution is None:
                raise EntityNotFound("Tool execution was not found.")
            if execution.status is not ToolExecutionStatus.UNKNOWN_OUTCOME:
                raise InvalidStateTransition(
                    "Only UNKNOWN_OUTCOME Tool executions can be reconciled."
                )
            reconciled = await uow.tool_executions.reconcile_unknown(
                execution_id=execution.id,
                result=dict(result),
                succeeded=succeeded,
                provider_request_id=provider_request_id,
                now=datetime.now(UTC),
            )
            if not reconciled:
                raise VersionConflict("Tool execution was reconciled concurrently.")
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
        async with self._unit_of_work_factory() as uow:
            run = await uow.runs.get(user_id=user_id, run_id=run_id)
            if run is None:
                raise EntityNotFound("Run was not found.")
            in_flight = await uow.tool_executions.list_in_progress(run_id=run_id)
            if in_flight:
                raise InvalidStateTransition(
                    "Cannot cancel while a Tool execution is in flight; "
                    "wait for its outcome to be persisted first."
                )
            await uow.rollback()
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
                    interaction = await uow.interactions.get(
                        user_id=user_id,
                        run_id=run_id,
                        interaction_id=interrupt_id,
                    )
                    if interaction is None:
                        raise InvalidStateTransition("Run Interaction was not found.")
                    interaction.resolve(response)
                    await uow.interactions.resolve(interaction)
                    run.resume(interrupt_id=interrupt_id, response=response)
                    event_data: dict[str, Any] = {
                        "status": RunStatus.QUEUED,
                        "label": run.status_label,
                        "phase": run.current_phase,
                    }
                    resumed = await uow.durable_jobs.resume(
                        user_id=user_id,
                        dedupe_key=f"agent-run:{run.id}",
                        now=datetime.now(UTC),
                    )
                    if not resumed:
                        raise InvalidStateTransition("Paused Durable Job was not found.")
                else:
                    run.cancel()
                    event_data = {"status": RunStatus.CANCELLED}
                    await uow.durable_jobs.cancel(
                        user_id=user_id,
                        dedupe_key=f"agent-run:{run.id}",
                        now=datetime.now(UTC),
                    )
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
            event_type = (
                RunEventType.RUN_RESUMED if operation == "RESUME" else RunEventType.RUN_CANCELLED
            )
            await uow.runs.append_event(
                run_id=run.id,
                event_type=event_type,
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
        after_sequence: int | None = None,
        limit: int = 200,
    ) -> list[RunEventDTO]:
        async with self._unit_of_work_factory() as uow:
            if await uow.runs.get(user_id=user_id, run_id=run_id) is None:
                raise EntityNotFound("Run was not found.")
            values = await uow.runs.list_events(
                user_id=user_id,
                run_id=run_id,
                after_event_id=after_event_id,
                after_sequence=after_sequence,
                limit=limit,
            )
            return [to_event_dto(value) for value in values]

    async def start_run(self, *, user_id: UUID, run_id: UUID, phase: str, label: str) -> RunDTO:
        return await self._worker_transition(
            user_id=user_id, run_id=run_id, action="START", phase=phase, label=label
        )

    async def require_input(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        payload: dict[str, Any],
        interaction_id: UUID | None = None,
        claim_owner: str | None = None,
        claim_token: UUID | None = None,
    ) -> RunDTO:
        return await self._worker_transition(
            user_id=user_id,
            run_id=run_id,
            action="WAIT",
            payload=payload,
            interaction_id=interaction_id,
            claim_owner=claim_owner,
            claim_token=claim_token,
        )

    async def complete_run(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        content: str,
        claim_owner: str | None = None,
        claim_token: UUID | None = None,
    ) -> RunDTO:
        return await self._worker_transition(
            user_id=user_id,
            run_id=run_id,
            action="COMPLETE",
            content=content,
            claim_owner=claim_owner,
            claim_token=claim_token,
        )

    async def accept_terminal_output(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        output: dict[str, Any],
        claim_owner: str,
        claim_token: UUID,
    ) -> RunDTO:
        async with self._unit_of_work_factory() as uow:
            run = await uow.runs.get(user_id=user_id, run_id=run_id)
            if run is None:
                raise EntityNotFound("Run was not found.")
            if run.claim_owner != claim_owner or run.claim_token != claim_token:
                raise InvalidStateTransition("Run lease is no longer owned by this worker.")
            expected_version = run.version
            try:
                run.accept_terminal_output(output)
            except ValueError as exception:
                raise InvalidStateTransition(str(exception)) from exception
            if run.version != expected_version and not await uow.runs.update(
                run, expected_version=expected_version
            ):
                raise VersionConflict("Run was updated concurrently.")
            await uow.commit()
            return to_run_dto(run)

    async def fail_run(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        error_code: str,
        claim_owner: str | None = None,
        claim_token: UUID | None = None,
    ) -> RunDTO:
        return await self._worker_transition(
            user_id=user_id,
            run_id=run_id,
            action="FAIL",
            error_code=error_code,
            claim_owner=claim_owner,
            claim_token=claim_token,
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
            event = await uow.runs.append_event(run_id=run_id, event_type=event_type, data=data)
            await uow.commit()
            result = to_event_dto(event)
        await self.publish_wakeup(run_id=run_id, latest_sequence=result.sequence)
        return result

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
        interaction_id: UUID | None = None,
        claim_owner: str | None = None,
        claim_token: UUID | None = None,
    ) -> RunDTO:
        async with self._unit_of_work_factory() as uow:
            run = await uow.runs.get(user_id=user_id, run_id=run_id)
            if run is None:
                raise EntityNotFound("Run was not found.")
            if claim_owner is not None and (
                claim_token is None
                or run.claim_owner != claim_owner
                or run.claim_token != claim_token
            ):
                raise InvalidStateTransition("Run lease is no longer owned by this worker.")
            expected_version = run.version
            try:
                if action == "START":
                    run.start(phase=phase, label=label)
                    event_type = RunEventType.RUN_STARTED
                    data: dict[str, Any] = {"phase": phase, "label": label}
                elif action == "WAIT":
                    assert payload is not None
                    interrupt_id = interaction_id or uuid4()
                    run.wait_for_user(interrupt_id=interrupt_id, payload=payload)
                    await uow.interactions.add(
                        RunInteraction(
                            id=interrupt_id,
                            user_id=user_id,
                            run_id=run.id,
                            action_id=(
                                str(payload["action_id"])
                                if payload.get("action_id") is not None
                                else None
                            ),
                            interaction_type=str(payload.get("type", "CONFIRMATION")),
                            request_payload=dict(payload),
                        )
                    )
                    event_type = RunEventType.HITL_REQUESTED
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
                    event_type=RunEventType.ASSISTANT_COMPLETED,
                    data={"message_id": data["message_id"], "content": content},
                )
            last_event = await uow.runs.append_event(
                run_id=run.id, event_type=event_type, data=data
            )
            if action == "WAIT":
                last_event = await uow.runs.append_event(
                    run_id=run.id,
                    event_type=RunEventType.RUN_WAITING_FOR_USER,
                    data={"interaction_id": data["interrupt_id"]},
                )
            await uow.commit()
            result = to_run_dto(run)
        await self.publish_wakeup(run_id=run_id, latest_sequence=last_event.sequence)
        return result
