from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from laoshiren.agent.contracts import ToolResult, ToolStatus
from laoshiren.application.automations.service import AutomationApplicationService
from laoshiren.application.files.evidence import web_evidence_ref
from laoshiren.application.memories.context import AgentMemoryApplicationService
from laoshiren.application.memories.manager import MemoryManager
from laoshiren.application.personal_state.service import PersonalStateApplicationService
from laoshiren.application.search.service import SearchApplicationService, normalize_search_query
from laoshiren.application.sources.service import SourceApplicationService
from laoshiren.domain.automations.entities import AutomationType
from laoshiren.domain.memories.entities import MemoryType
from laoshiren.domain.personal_state.exceptions import (
    EntityNotFound,
    InvalidStateTransition,
    VersionConflict,
)
from laoshiren.domain.personal_state.value_objects import (
    BlockerSeverity,
    DateCertainty,
    DatePrecision,
    TaskStatus,
    ThingDateType,
    ThingStatus,
)

ToolHandler = Callable[["ToolExecutionContext", dict[str, Any]], Awaitable[ToolResult]]

V2_2_CAPABILITY_NAMES: frozenset[str] = frozenset(
    {
        "state_get_overview",
        "state_get_thing_context",
        "thing_create",
        "thing_change_state",
        "task_create",
        "task_change_status",
        "thing_date_set",
        "thing_context_set",
        "blocker_manage",
        "memory_search",
        "memory_remember",
        "memory_forget",
        "file_search",
        "file_inspect",
        "search_web",
        "url_inspect",
        "automation_create",
        "automation_cancel",
        "thing_merge",
        "thing_delete",
        "file_delete",
    }
)


class ToolRisk(StrEnum):
    READ = "READ"
    REVERSIBLE_WRITE = "REVERSIBLE_WRITE"
    SENSITIVE_WRITE = "SENSITIVE_WRITE"
    IRREVERSIBLE = "IRREVERSIBLE"


class ToolReplayPolicy(StrEnum):
    READ_ONLY = "READ_ONLY"
    IDEMPOTENT = "IDEMPOTENT"
    NON_REPLAYABLE = "NON_REPLAYABLE"


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    user_id: UUID
    run_id: UUID
    action_id: str
    tool_claim_owner: str | None = None
    tool_claim_token: UUID | None = None

    @property
    def idempotency_key(self) -> str:
        """Stable key that every downstream side-effect adapter must propagate."""
        return f"agent:{self.run_id}:{self.action_id}"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    risk: ToolRisk
    handler: ToolHandler
    replay_policy: ToolReplayPolicy = ToolReplayPolicy.READ_ONLY
    enabled: bool = True
    required_arguments: tuple[str, ...] = ()


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._definitions:
            raise ValueError(f"Tool is already registered: {definition.name}")
        if (
            definition.risk is not ToolRisk.READ
            and definition.replay_policy is ToolReplayPolicy.READ_ONLY
        ):
            raise ValueError("Write Tools must declare an explicit replay policy.")
        if (
            definition.risk is ToolRisk.READ
            and definition.replay_policy is not ToolReplayPolicy.READ_ONLY
        ):
            raise ValueError("Read Tools must use the READ_ONLY replay policy.")
        self._definitions[definition.name] = definition

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(name for name, item in self._definitions.items() if item.enabled))

    def get(self, name: str) -> ToolDefinition | None:
        definition = self._definitions.get(name)
        return definition if definition is not None and definition.enabled else None

    async def execute(
        self, *, name: str, context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        definition = self.get(name)
        if definition is None:
            return ToolResult(ToolStatus.NOT_FOUND, "TOOL_NOT_FOUND", "Tool is unavailable.")
        missing = [key for key in definition.required_arguments if key not in arguments]
        if missing:
            return ToolResult(
                ToolStatus.REQUIRES_USER_INPUT,
                "MISSING_ARGUMENT",
                "Required tool arguments are missing.",
                data={"missing": missing},
            )
        try:
            return await definition.handler(context, arguments)
        except EntityNotFound:
            return ToolResult(
                ToolStatus.NOT_FOUND,
                "ENTITY_NOT_FOUND",
                "Requested data was not found.",
            )
        except VersionConflict:
            return ToolResult(
                ToolStatus.CONFLICT,
                "VERSION_CONFLICT",
                "Data changed concurrently; reload before retrying.",
                retryable=True,
            )
        except InvalidStateTransition:
            return ToolResult(
                ToolStatus.CONFLICT,
                "INVALID_STATE_TRANSITION",
                "The requested state transition is not allowed.",
            )
        except (KeyError, TypeError, ValueError):
            return ToolResult(ToolStatus.FAILED, "INVALID_ARGUMENT", "Tool arguments are invalid.")


def _ledger_ready(runtime: Any | None, context: ToolExecutionContext) -> bool:
    return (
        runtime is not None
        and context.tool_claim_owner is not None
        and context.tool_claim_token is not None
    )


async def try_bound_mutation(
    runtime: Any | None,
    context: ToolExecutionContext,
    *,
    tool_name: str,
    code: str,
    message: str,
    apply_mutation: Any,
) -> ToolResult | None:
    if not _ledger_ready(runtime, context):
        return None
    complete = getattr(runtime, "complete_mutation_tool", None) or getattr(
        runtime, "complete_personal_state_mutation_tool", None
    )
    if complete is None:
        return None
    data = await complete(
        user_id=context.user_id,
        run_id=context.run_id,
        action_id=context.action_id,
        owner=context.tool_claim_owner,
        claim_token=context.tool_claim_token,
        tool_name=tool_name,
        apply_mutation=apply_mutation,
    )
    mutation_id = data.get("mutation_id")
    mutation_refs = (str(mutation_id),) if mutation_id else ()
    return ToolResult(
        ToolStatus.SUCCESS,
        code,
        message,
        data=data,
        mutation_refs=mutation_refs,
        ledger_receipt_persisted=True,
    )


def register_personal_state_tools(
    registry: ToolRegistry,
    service: PersonalStateApplicationService,
    runtime: Any | None = None,
) -> None:
    from laoshiren.application.personal_state import write_ops

    async def try_bound(
        context: ToolExecutionContext,
        *,
        tool_name: str,
        code: str,
        message: str,
        apply_mutation: Any,
    ) -> ToolResult | None:
        return await try_bound_mutation(
            runtime,
            context,
            tool_name=tool_name,
            code=code,
            message=message,
            apply_mutation=apply_mutation,
        )

    def idempotency_key(context: ToolExecutionContext) -> str:
        return context.idempotency_key

    async def create_thing(context: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        bound = await try_bound(
            context,
            tool_name="thing_create",
            code="THING_CREATED",
            message="Thing created.",
            apply_mutation=lambda uow: write_ops.apply_create_thing(
                uow,
                user_id=context.user_id,
                name=str(arguments["name"]),
                action_id=context.action_id,
                idempotency_key=idempotency_key(context),
                reason=str(arguments.get("reason", "Agent-created Thing")),
                run_id=context.run_id,
            ),
        )
        if bound is not None:
            return bound
        thing = await service.create_thing(
            user_id=context.user_id,
            name=str(arguments["name"]),
            action_id=context.action_id,
            idempotency_key=idempotency_key(context),
            reason=str(arguments.get("reason", "Agent-created Thing")),
            run_id=context.run_id,
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "THING_CREATED",
            "Thing created.",
            data={"id": str(thing.id), "version": thing.version},
        )

    async def create_task(context: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        thing_id_raw = arguments.get("thing_id")
        due_at_raw = arguments.get("due_at")
        bound = await try_bound(
            context,
            tool_name="task_create",
            code="TASK_CREATED",
            message="Task created.",
            apply_mutation=lambda uow: write_ops.apply_create_task(
                uow,
                user_id=context.user_id,
                thing_id=UUID(str(thing_id_raw)) if thing_id_raw else None,
                title=str(arguments["title"]),
                due_at=datetime.fromisoformat(str(due_at_raw)) if due_at_raw else None,
                recurrence_interval_days=(
                    int(arguments["recurrence_interval_days"])
                    if arguments.get("recurrence_interval_days") is not None
                    else None
                ),
                action_id=context.action_id,
                idempotency_key=idempotency_key(context),
                reason=str(arguments.get("reason", "Agent-created Task")),
                run_id=context.run_id,
            ),
        )
        if bound is not None:
            return bound
        task = await service.create_task(
            user_id=context.user_id,
            thing_id=UUID(str(thing_id_raw)) if thing_id_raw else None,
            title=str(arguments["title"]),
            due_at=datetime.fromisoformat(str(due_at_raw)) if due_at_raw else None,
            recurrence_interval_days=(
                int(arguments["recurrence_interval_days"])
                if arguments.get("recurrence_interval_days") is not None
                else None
            ),
            action_id=context.action_id,
            idempotency_key=idempotency_key(context),
            reason=str(arguments.get("reason", "Agent-created Task")),
            run_id=context.run_id,
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "TASK_CREATED",
            "Task created.",
            data={"id": str(task.id), "version": task.version},
        )

    async def set_deadline(context: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        source_id_raw = arguments.get("source_id")
        source_id = UUID(str(source_id_raw)) if source_id_raw else None
        bound = await try_bound(
            context,
            tool_name="thing_date_set",
            code="DEADLINE_SET",
            message="Deadline set.",
            apply_mutation=lambda uow: write_ops.apply_set_deadline(
                uow,
                user_id=context.user_id,
                thing_id=UUID(str(arguments["thing_id"])),
                kind=ThingDateType(str(arguments.get("kind", "DEADLINE"))),
                label=str(arguments["label"]) if arguments.get("label") else None,
                value=datetime.fromisoformat(str(arguments["value"])),
                timezone_name=str(arguments["timezone"]),
                precision=DatePrecision(str(arguments.get("precision", "DATE_TIME"))),
                certainty=DateCertainty(str(arguments["certainty"])),
                is_primary=bool(arguments.get("is_primary", True)),
                expected_version=int(arguments["expected_version"]),
                action_id=context.action_id,
                idempotency_key=idempotency_key(context),
                reason=str(arguments.get("reason", "Agent set deadline")),
                run_id=context.run_id,
                source_id=source_id,
            ),
        )
        if bound is not None:
            return bound
        result = await service.set_deadline(
            user_id=context.user_id,
            thing_id=UUID(str(arguments["thing_id"])),
            kind=ThingDateType(str(arguments.get("kind", "DEADLINE"))),
            label=str(arguments["label"]) if arguments.get("label") else None,
            value=datetime.fromisoformat(str(arguments["value"])),
            timezone_name=str(arguments["timezone"]),
            precision=DatePrecision(str(arguments.get("precision", "DATE_TIME"))),
            certainty=DateCertainty(str(arguments["certainty"])),
            is_primary=bool(arguments.get("is_primary", True)),
            expected_version=int(arguments["expected_version"]),
            action_id=context.action_id,
            idempotency_key=idempotency_key(context),
            reason=str(arguments.get("reason", "Agent set deadline")),
            run_id=context.run_id,
            source_id=source_id,
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "DEADLINE_SET",
            "Deadline set.",
            data={
                "mutation_id": str(result.mutation_id),
                "date_id": str(result.target_id),
                "thing_version": result.target_version,
                "replayed": result.replayed,
            },
            mutation_refs=(str(result.mutation_id),),
        )

    async def get_thing_context(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        thing_id = UUID(str(arguments["thing_id"]))
        payload = await service.get_thing_context_snapshot(
            user_id=context.user_id,
            thing_id=thing_id,
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "OK",
            "Current Thing context loaded.",
            data=payload,
        )

    async def get_state_overview(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        overview = await service.get_state_overview(user_id=context.user_id)
        return ToolResult(
            ToolStatus.SUCCESS,
            "OK",
            "Authoritative current-state overview loaded.",
            data={
                "active": [
                    {"thing_id": str(item.thing_id), "version": None} for item in overview.active
                ],
                "upcoming": [{"thing_id": str(item.thing_id)} for item in overview.upcoming],
                "blocked": [{"thing_id": str(item.thing_id)} for item in overview.blocked],
                "recent": [
                    {"thing_id": str(item.thing_id), "version": None} for item in overview.recent
                ],
            },
        )

    async def set_thing_context(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        entry_id = arguments.get("entry_id")
        bound = await try_bound(
            context,
            tool_name="thing_context_set",
            code="THING_CONTEXT_SET",
            message="Current Thing context set.",
            apply_mutation=lambda uow: write_ops.apply_set_thing_context(
                uow,
                user_id=context.user_id,
                thing_id=UUID(str(arguments["thing_id"])),
                label=str(arguments["label"]),
                content=str(arguments["content"]),
                entry_id=UUID(str(entry_id)) if entry_id else None,
                expected_version=arguments.get("expected_version"),
                source_id=None,
                action_id=context.action_id,
                idempotency_key=idempotency_key(context),
                reason=str(arguments.get("reason", "Agent updated current Thing context.")),
                run_id=context.run_id,
            ),
        )
        if bound is not None:
            return bound
        result = await service.set_thing_context(
            user_id=context.user_id,
            thing_id=UUID(str(arguments["thing_id"])),
            label=str(arguments["label"]),
            content=str(arguments["content"]),
            entry_id=UUID(str(entry_id)) if entry_id else None,
            expected_version=arguments.get("expected_version"),
            source_id=None,
            action_id=context.action_id,
            idempotency_key=idempotency_key(context),
            reason=str(arguments.get("reason", "Agent updated current Thing context.")),
            run_id=context.run_id,
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "THING_CONTEXT_SET",
            "Current Thing context set.",
            data={
                "mutation_id": str(result.mutation_id),
                "entry_id": str(result.target_id),
                "version": result.target_version,
                "replayed": result.replayed,
            },
            mutation_refs=(str(result.mutation_id),),
        )

    async def change_thing_state(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        action = str(arguments["action"])
        if action == "ARCHIVE":
            return await archive_thing(context, arguments)
        if action == "RESTORE":
            bound = await try_bound(
                context,
                tool_name="thing_change_state",
                code="THING_RESTORED",
                message="Thing restored.",
                apply_mutation=lambda uow: write_ops.apply_change_archive(
                    uow,
                    user_id=context.user_id,
                    thing_id=UUID(str(arguments["thing_id"])),
                    expected_version=int(arguments["expected_version"]),
                    action_id=context.action_id,
                    idempotency_key=idempotency_key(context),
                    reason=str(arguments.get("reason", "Agent restored Thing")),
                    run_id=context.run_id,
                    archive=False,
                ),
            )
            if bound is not None:
                return bound
            result = await service.unarchive_thing(
                user_id=context.user_id,
                thing_id=UUID(str(arguments["thing_id"])),
                expected_version=int(arguments["expected_version"]),
                action_id=context.action_id,
                idempotency_key=idempotency_key(context),
                reason=str(arguments.get("reason", "Agent restored Thing")),
                run_id=context.run_id,
            )
            return ToolResult(
                ToolStatus.SUCCESS,
                "THING_RESTORED",
                "Thing restored.",
                data={"mutation_id": str(result.mutation_id), "version": result.target_version},
                mutation_refs=(str(result.mutation_id),),
            )
        status_by_action = {
            "COMPLETE": ThingStatus.COMPLETED,
            "CANCEL": ThingStatus.CANCELLED,
            "REACTIVATE": ThingStatus.ACTIVE,
        }
        status = status_by_action.get(action)
        if status is None:
            raise ValueError("Unsupported Thing state action.")
        thing = await service.update_thing(
            user_id=context.user_id,
            thing_id=UUID(str(arguments["thing_id"])),
            expected_version=int(arguments["expected_version"]),
            name=None,
            status=status,
            current_stage=None,
            update_current_stage=False,
            action_id=context.action_id,
            idempotency_key=idempotency_key(context),
            reason=str(arguments.get("reason", f"Agent {action.lower()} Thing")),
            run_id=context.run_id,
        )
        code_by_action = {
            "COMPLETE": "THING_COMPLETED",
            "CANCEL": "THING_CANCELLED",
            "REACTIVATE": "THING_REACTIVATED",
        }
        return ToolResult(
            ToolStatus.SUCCESS,
            code_by_action[action],
            f"Thing {action.lower()}d.",
            data={"id": str(thing.id), "version": thing.version},
        )

    async def manage_blocker(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        if str(arguments["operation"]) == "OPEN":
            return await create_blocker(context, arguments)
        if str(arguments["operation"]) == "RESOLVE":
            return await resolve_blocker(context, arguments)
        raise ValueError("Unsupported Blocker operation.")

    async def set_thing_date(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        if str(arguments["operation"]) == "CREATE":
            return await set_deadline(context, arguments)
        if str(arguments["operation"]) == "CORRECT":
            return await update_date(context, arguments)
        raise ValueError("Unsupported ThingDate operation.")

    async def transition_task(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        bound = await try_bound(
            context,
            tool_name="task_change_status",
            code="TASK_STATUS_CHANGED",
            message="Task status changed.",
            apply_mutation=lambda uow: write_ops.apply_transition_task(
                uow,
                user_id=context.user_id,
                task_id=UUID(str(arguments["task_id"])),
                target_status=TaskStatus(str(arguments["target_status"])),
                expected_version=int(arguments["expected_version"]),
                action_id=context.action_id,
                idempotency_key=idempotency_key(context),
                reason=str(arguments.get("reason", "Agent changed Task status")),
                run_id=context.run_id,
            ),
        )
        if bound is not None:
            return bound
        result = await service.transition_task(
            user_id=context.user_id,
            task_id=UUID(str(arguments["task_id"])),
            target_status=TaskStatus(str(arguments["target_status"])),
            expected_version=int(arguments["expected_version"]),
            action_id=context.action_id,
            idempotency_key=idempotency_key(context),
            reason=str(arguments.get("reason", "Agent changed Task status")),
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "TASK_STATUS_CHANGED",
            "Task status changed.",
            data={
                "mutation_id": str(result.mutation_id),
                "task_id": str(result.target_id),
                "version": result.target_version,
                "replayed": result.replayed,
            },
            mutation_refs=(str(result.mutation_id),),
        )

    async def create_blocker(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        bound = await try_bound(
            context,
            tool_name="blocker_manage",
            code="BLOCKER_ADDED",
            message="Blocker added.",
            apply_mutation=lambda uow: write_ops.apply_create_blocker(
                uow,
                user_id=context.user_id,
                thing_id=UUID(str(arguments["thing_id"])),
                description=str(arguments["description"]),
                severity=BlockerSeverity(str(arguments.get("severity", "MEDIUM"))),
                task_id=UUID(str(arguments["task_id"])) if arguments.get("task_id") else None,
                source_id=None,
                action_id=context.action_id,
                idempotency_key=idempotency_key(context),
                reason=str(arguments.get("reason", "Agent added Blocker")),
            ),
        )
        if bound is not None:
            return bound
        blocker = await service.create_blocker(
            user_id=context.user_id,
            thing_id=UUID(str(arguments["thing_id"])),
            description=str(arguments["description"]),
            severity=BlockerSeverity(str(arguments.get("severity", "MEDIUM"))),
            task_id=UUID(str(arguments["task_id"])) if arguments.get("task_id") else None,
            source_id=None,
            action_id=context.action_id,
            idempotency_key=idempotency_key(context),
            reason=str(arguments.get("reason", "Agent added Blocker")),
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "BLOCKER_ADDED",
            "Blocker added.",
            data={"id": str(blocker.id), "version": blocker.version},
        )

    async def resolve_blocker(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        bound = await try_bound(
            context,
            tool_name="blocker_manage",
            code="BLOCKER_RESOLVED",
            message="Blocker resolved.",
            apply_mutation=lambda uow: write_ops.apply_resolve_blocker(
                uow,
                user_id=context.user_id,
                blocker_id=UUID(str(arguments["blocker_id"])),
                expected_version=int(arguments["expected_version"]),
                action_id=context.action_id,
                idempotency_key=idempotency_key(context),
                reason=str(arguments.get("reason", "Agent resolved Blocker")),
            ),
        )
        if bound is not None:
            return bound
        result = await service.resolve_blocker(
            user_id=context.user_id,
            blocker_id=UUID(str(arguments["blocker_id"])),
            expected_version=int(arguments["expected_version"]),
            action_id=context.action_id,
            idempotency_key=idempotency_key(context),
            reason=str(arguments.get("reason", "Agent resolved Blocker")),
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "BLOCKER_RESOLVED",
            "Blocker resolved.",
            data={
                "mutation_id": str(result.mutation_id),
                "blocker_id": str(result.target_id),
                "version": result.target_version,
                "replayed": result.replayed,
            },
            mutation_refs=(str(result.mutation_id),),
        )

    async def update_date(context: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        bound = await try_bound(
            context,
            tool_name="thing_date_set",
            code="DATE_UPDATED",
            message="Date updated.",
            apply_mutation=lambda uow: write_ops.apply_update_date(
                uow,
                user_id=context.user_id,
                date_id=UUID(str(arguments["date_id"])),
                value=datetime.fromisoformat(str(arguments["value"])),
                timezone_name=str(arguments["timezone"]),
                precision=DatePrecision(str(arguments.get("precision", "DATE_TIME"))),
                certainty=DateCertainty(str(arguments["certainty"])),
                is_primary=bool(arguments.get("is_primary", False)),
                expected_version=int(arguments["expected_version"]),
                expected_thing_version=int(arguments["expected_thing_version"]),
                action_id=context.action_id,
                idempotency_key=idempotency_key(context),
                reason=str(arguments.get("reason", "Agent updated date")),
            ),
        )
        if bound is not None:
            return bound
        result = await service.update_date(
            user_id=context.user_id,
            date_id=UUID(str(arguments["date_id"])),
            value=datetime.fromisoformat(str(arguments["value"])),
            timezone_name=str(arguments["timezone"]),
            precision=DatePrecision(str(arguments.get("precision", "DATE_TIME"))),
            certainty=DateCertainty(str(arguments["certainty"])),
            is_primary=bool(arguments.get("is_primary", False)),
            expected_version=int(arguments["expected_version"]),
            expected_thing_version=int(arguments["expected_thing_version"]),
            action_id=context.action_id,
            idempotency_key=idempotency_key(context),
            reason=str(arguments.get("reason", "Agent updated date")),
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "DATE_UPDATED",
            "Date updated.",
            data={
                "mutation_id": str(result.mutation_id),
                "date_id": str(result.target_id),
                "thing_version": result.target_version,
                "replayed": result.replayed,
            },
            mutation_refs=(str(result.mutation_id),),
        )

    async def archive_thing(context: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        bound = await try_bound(
            context,
            tool_name="thing_change_state",
            code="THING_ARCHIVED",
            message="Thing archived.",
            apply_mutation=lambda uow: write_ops.apply_change_archive(
                uow,
                user_id=context.user_id,
                thing_id=UUID(str(arguments["thing_id"])),
                expected_version=int(arguments["expected_version"]),
                action_id=context.action_id,
                idempotency_key=idempotency_key(context),
                reason=str(arguments.get("reason", "Agent archived Thing")),
                run_id=context.run_id,
                archive=True,
            ),
        )
        if bound is not None:
            return bound
        result = await service.archive_thing(
            user_id=context.user_id,
            thing_id=UUID(str(arguments["thing_id"])),
            expected_version=int(arguments["expected_version"]),
            action_id=context.action_id,
            idempotency_key=idempotency_key(context),
            reason=str(arguments.get("reason", "Agent archived Thing")),
            run_id=context.run_id,
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "THING_ARCHIVED",
            "Thing archived.",
            data={
                "mutation_id": str(result.mutation_id),
                "thing_id": str(result.target_id),
                "version": result.target_version,
                "replayed": result.replayed,
            },
            mutation_refs=(str(result.mutation_id),),
        )

    async def delete_thing(context: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        bound = await try_bound(
            context,
            tool_name="thing_delete",
            code="THING_DELETED",
            message="Thing deleted.",
            apply_mutation=lambda uow: write_ops.apply_delete_thing(
                uow,
                user_id=context.user_id,
                thing_id=UUID(str(arguments["thing_id"])),
                expected_version=int(arguments["expected_version"]),
                action_id=context.action_id,
                idempotency_key=idempotency_key(context),
                reason=str(arguments.get("reason", "Agent deleted Thing.")),
                run_id=context.run_id,
            ),
        )
        if bound is not None:
            return bound
        result = await service.delete_thing(
            user_id=context.user_id,
            thing_id=UUID(str(arguments["thing_id"])),
            expected_version=int(arguments["expected_version"]),
            action_id=context.action_id,
            idempotency_key=idempotency_key(context),
            reason=str(arguments.get("reason", "Agent deleted Thing.")),
            run_id=context.run_id,
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "THING_DELETED",
            "Thing deleted.",
            data={
                "mutation_id": str(result.mutation_id),
                "thing_id": str(result.target_id),
                "version": result.target_version,
                "replayed": result.replayed,
            },
            mutation_refs=(str(result.mutation_id),),
        )

    async def merge_things(context: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        bound = await try_bound(
            context,
            tool_name="thing_merge",
            code="THING_MERGED",
            message="Duplicate Thing merged into its canonical Thing.",
            apply_mutation=lambda uow: write_ops.apply_merge_things(
                uow,
                user_id=context.user_id,
                canonical_thing_id=UUID(str(arguments["canonical_thing_id"])),
                duplicate_thing_id=UUID(str(arguments["duplicate_thing_id"])),
                expected_canonical_version=int(arguments["expected_canonical_version"]),
                expected_duplicate_version=int(arguments["expected_duplicate_version"]),
                action_id=context.action_id,
                idempotency_key=idempotency_key(context),
                reason=str(arguments.get("reason", "Agent merged duplicate Things.")),
                run_id=context.run_id,
            ),
        )
        if bound is not None:
            return bound
        result = await service.merge_things(
            user_id=context.user_id,
            canonical_thing_id=UUID(str(arguments["canonical_thing_id"])),
            duplicate_thing_id=UUID(str(arguments["duplicate_thing_id"])),
            expected_canonical_version=int(arguments["expected_canonical_version"]),
            expected_duplicate_version=int(arguments["expected_duplicate_version"]),
            action_id=context.action_id,
            idempotency_key=idempotency_key(context),
            reason=str(arguments.get("reason", "Agent merged duplicate Things.")),
            run_id=context.run_id,
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "THING_MERGED",
            "Duplicate Thing merged into its canonical Thing.",
            data={
                "mutation_id": str(result.mutation_id),
                "duplicate_thing_id": str(result.target_id),
                "version": result.target_version,
                "replayed": result.replayed,
            },
            mutation_refs=(str(result.mutation_id),),
        )

    for definition in (
        ToolDefinition(
            "state_get_overview",
            "Read the bounded authoritative current-state overview.",
            ToolRisk.READ,
            get_state_overview,
        ),
        ToolDefinition(
            "state_get_thing_context",
            "Read one Thing's current state with stable versions.",
            ToolRisk.READ,
            get_thing_context,
            required_arguments=("thing_id",),
        ),
        ToolDefinition(
            "thing_create",
            "Create a persistent Thing.",
            ToolRisk.REVERSIBLE_WRITE,
            create_thing,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("name",),
        ),
        ToolDefinition(
            "task_create",
            "Create a standalone or Thing-linked Task.",
            ToolRisk.REVERSIBLE_WRITE,
            create_task,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("title",),
        ),
        ToolDefinition(
            "task_change_status",
            "Change a Task status with optimistic concurrency.",
            ToolRisk.REVERSIBLE_WRITE,
            transition_task,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("task_id", "target_status", "expected_version"),
        ),
        ToolDefinition(
            "thing_context_set",
            "Create or correct one current soft-state entry.",
            ToolRisk.REVERSIBLE_WRITE,
            set_thing_context,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("thing_id", "label", "content"),
        ),
        ToolDefinition(
            "thing_merge",
            "Merge a duplicate Thing after confirmation.",
            ToolRisk.IRREVERSIBLE,
            merge_things,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=(
                "canonical_thing_id",
                "duplicate_thing_id",
                "expected_canonical_version",
                "expected_duplicate_version",
            ),
        ),
        ToolDefinition(
            "thing_change_state",
            "Change Thing lifecycle or archive state.",
            ToolRisk.REVERSIBLE_WRITE,
            change_thing_state,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("thing_id", "action", "expected_version"),
        ),
        ToolDefinition(
            "thing_date_set",
            "Create or correct a typed ThingDate.",
            ToolRisk.SENSITIVE_WRITE,
            set_thing_date,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("operation",),
        ),
        ToolDefinition(
            "blocker_manage",
            "Open or resolve a Blocker.",
            ToolRisk.REVERSIBLE_WRITE,
            manage_blocker,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("operation",),
        ),
        ToolDefinition(
            "thing_delete",
            "Permanently delete a Thing after confirmation.",
            ToolRisk.IRREVERSIBLE,
            delete_thing,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("thing_id", "expected_version"),
        ),
    ):
        registry.register(definition)


def register_automation_tools(
    registry: ToolRegistry,
    service: AutomationApplicationService,
    runtime: Any | None = None,
) -> None:
    from laoshiren.application.automations import write_ops as automation_write_ops

    def idempotency_key(context: ToolExecutionContext) -> str:
        return context.idempotency_key

    async def create_automation(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        bound = await try_bound_mutation(
            runtime,
            context,
            tool_name="automation_create",
            code="AUTOMATION_CREATED",
            message="Automation created.",
            apply_mutation=lambda uow: automation_write_ops.apply_create_automation(
                uow,
                user_id=context.user_id,
                automation_type=AutomationType(str(arguments["automation_type"])),
                title=str(arguments["title"]),
                message=str(arguments.get("message", arguments["title"])),
                timezone_name=str(arguments.get("timezone", "Asia/Shanghai")),
                next_trigger_at=datetime.fromisoformat(str(arguments["next_trigger_at"])),
                idempotency_key=idempotency_key(context),
                thing_id=UUID(str(arguments["thing_id"])) if arguments.get("thing_id") else None,
                task_id=UUID(str(arguments["task_id"])) if arguments.get("task_id") else None,
                recurrence_interval_seconds=(
                    int(arguments["recurrence_interval_seconds"])
                    if arguments.get("recurrence_interval_seconds")
                    else None
                ),
            ),
        )
        if bound is not None:
            return bound
        automation = await service.create(
            user_id=context.user_id,
            automation_type=AutomationType(str(arguments["automation_type"])),
            title=str(arguments["title"]),
            message=str(arguments.get("message", arguments["title"])),
            timezone_name=str(arguments.get("timezone", "Asia/Shanghai")),
            next_trigger_at=datetime.fromisoformat(str(arguments["next_trigger_at"])),
            idempotency_key=idempotency_key(context),
            thing_id=UUID(str(arguments["thing_id"])) if arguments.get("thing_id") else None,
            task_id=UUID(str(arguments["task_id"])) if arguments.get("task_id") else None,
            recurrence_interval_seconds=(
                int(arguments["recurrence_interval_seconds"])
                if arguments.get("recurrence_interval_seconds")
                else None
            ),
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "AUTOMATION_CREATED",
            "Automation created.",
            data={
                "id": str(automation.id),
                "status": automation.status.value,
                "version": automation.version,
            },
        )

    async def change_automation(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        action = str(arguments["action"])
        code = "AUTOMATION_CANCELLED" if action == "CANCEL" else "AUTOMATION_CHANGED"
        bound = await try_bound_mutation(
            runtime,
            context,
            tool_name="automation_cancel" if action == "CANCEL" else "automation_create",
            code=code,
            message="Automation status changed.",
            apply_mutation=lambda uow: automation_write_ops.apply_change_automation_status(
                uow,
                user_id=context.user_id,
                automation_id=UUID(str(arguments["automation_id"])),
                action=action,
                expected_version=int(arguments["expected_version"]),
                idempotency_key=idempotency_key(context),
            ),
        )
        if bound is not None:
            return bound
        automation = await service.change_status(
            user_id=context.user_id,
            automation_id=UUID(str(arguments["automation_id"])),
            action=str(arguments["action"]),
            expected_version=int(arguments["expected_version"]),
            idempotency_key=idempotency_key(context),
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "AUTOMATION_CHANGED",
            "Automation status changed.",
            data={
                "id": str(automation.id),
                "status": automation.status.value,
                "version": automation.version,
            },
        )

    async def cancel_automation(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        return await change_automation(context, {**arguments, "action": "CANCEL"})

    registry.register(
        ToolDefinition(
            "automation_create",
            "Create an automation.",
            ToolRisk.REVERSIBLE_WRITE,
            create_automation,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("automation_type", "title", "next_trigger_at"),
        )
    )
    registry.register(
        ToolDefinition(
            "automation_cancel",
            "Cancel an automation with optimistic concurrency.",
            ToolRisk.REVERSIBLE_WRITE,
            cancel_automation,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("automation_id", "expected_version"),
        )
    )


def register_memory_tools(
    registry: ToolRegistry,
    memory: AgentMemoryApplicationService,
    manager: MemoryManager | None = None,
    runtime: Any | None = None,
) -> None:
    from laoshiren.application.memories import write_ops as memory_write_ops
    from laoshiren.application.memories.candidate import rejects_state_authority

    async def search(context: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        results = await memory.search(
            user_id=context.user_id,
            query=str(arguments["query"]),
            limit=int(arguments.get("limit", 8)),
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "OK",
            "Memories loaded.",
            data={
                "items": [
                    {
                        "id": str(item.id),
                        "type": item.memory_type.value,
                        "content": item.content,
                        "summary": item.summary,
                        "confidence": item.confidence,
                    }
                    for item in results
                ]
            },
        )

    async def remember(context: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        content = str(arguments["content"])
        if rejects_state_authority(content):
            return ToolResult(
                ToolStatus.FAILED,
                "STATE_AUTHORITY_VIOLATION",
                "Memory must not override current Personal State authority.",
            )
        bound = await try_bound_mutation(
            runtime,
            context,
            tool_name="memory_remember",
            code="MEMORY_REMEMBERED",
            message="Memory remembered.",
            apply_mutation=lambda uow: memory_write_ops.apply_explicit_remember(
                uow,
                user_id=context.user_id,
                run_id=context.run_id,
                content=content,
                memory_type=MemoryType(str(arguments["memory_type"])),
                idempotency_key=context.idempotency_key,
                thing_id=UUID(str(arguments["thing_id"])) if arguments.get("thing_id") else None,
            ),
        )
        if bound is not None:
            return bound
        if manager is None:
            return ToolResult(
                ToolStatus.NOT_FOUND,
                "MEMORY_MANAGER_UNAVAILABLE",
                "Memory manager is not configured.",
            )
        formed = await manager.remember(
            user_id=context.user_id,
            run_id=context.run_id,
            content=str(arguments["content"]),
            memory_type=MemoryType(str(arguments["memory_type"])),
            thing_id=UUID(str(arguments["thing_id"])) if arguments.get("thing_id") else None,
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "MEMORY_REMEMBERED",
            "Memory remembered.",
            data={"id": str(formed.id), "type": formed.memory_type.value},
        )

    async def forget(context: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        bound = await try_bound_mutation(
            runtime,
            context,
            tool_name="memory_forget",
            code="MEMORY_FORGOTTEN",
            message="Memory forgotten.",
            apply_mutation=lambda uow: memory_write_ops.apply_forget_memory(
                uow,
                user_id=context.user_id,
                memory_id=UUID(str(arguments["memory_id"])),
                expected_version=int(arguments["expected_version"]),
                idempotency_key=context.idempotency_key,
            ),
        )
        if bound is not None:
            return bound
        if manager is None:
            return ToolResult(
                ToolStatus.NOT_FOUND,
                "MEMORY_MANAGER_UNAVAILABLE",
                "Memory manager is not configured.",
            )
        memory = await manager.forget(
            user_id=context.user_id,
            memory_id=UUID(str(arguments["memory_id"])),
            expected_version=int(arguments["expected_version"]),
            idempotency_key=context.idempotency_key,
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "MEMORY_FORGOTTEN",
            "Memory forgotten.",
            data={"id": str(memory.id)},
        )

    for definition in (
        ToolDefinition(
            "memory_search",
            "Search long-term memory.",
            ToolRisk.READ,
            search,
            required_arguments=("query",),
        ),
        ToolDefinition(
            "memory_remember",
            "Persist an explicit long-term memory.",
            ToolRisk.REVERSIBLE_WRITE,
            remember,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("content", "memory_type"),
        ),
        ToolDefinition(
            "memory_forget",
            "Forget one resolved memory.",
            ToolRisk.SENSITIVE_WRITE,
            forget,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("memory_id", "expected_version"),
        ),
    ):
        registry.register(definition)


def register_source_tools(
    registry: ToolRegistry,
    service: SourceApplicationService,
    runtime: Any | None = None,
) -> None:
    from laoshiren.application.sources import write_ops as source_write_ops

    def idempotency_key(context: ToolExecutionContext) -> str:
        return context.idempotency_key

    def resolve_file_id(arguments: dict[str, Any]) -> UUID:
        raw = arguments.get("file_id") or arguments.get("source_id")
        return UUID(str(raw))

    async def inspect_file(context: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        source_id = resolve_file_id(arguments)
        source = await service.get(user_id=context.user_id, source_id=source_id)
        query = str(arguments.get("question", "")).strip() or None
        chunks = await service.get_context_chunks(
            user_id=context.user_id,
            source_id=source_id,
            query=query,
            max_chunks=int(arguments.get("limit", 8)),
            max_characters=int(arguments.get("max_characters", 12_000)),
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "OK",
            "File inspected.",
            data={
                "file_id": str(source.id),
                "title": source.title,
                "mime_type": source.mime_type,
                "processing_status": source.processing_status.value,
                "chunks": [
                    {
                        "segment_id": str(chunk.id),
                        "chunk_id": str(chunk.id),
                        "ordinal": chunk.ordinal,
                        "content": chunk.content,
                    }
                    for chunk in chunks
                ],
            },
        )

    async def search_files(context: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        thing_id = arguments.get("thing_id")
        items = await service.search_files(
            user_id=context.user_id,
            query=str(arguments["query"]),
            thing_id=UUID(str(thing_id)) if thing_id else None,
            limit=int(arguments.get("limit", 8)),
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "OK",
            "Matching files loaded.",
            data={"items": items},
        )

    async def delete_file(context: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        source_id = resolve_file_id(arguments)
        bound = await try_bound_mutation(
            runtime,
            context,
            tool_name="file_delete",
            code="FILE_DELETED",
            message="File deleted.",
            apply_mutation=lambda uow: source_write_ops.apply_delete_file(
                uow,
                user_id=context.user_id,
                source_id=source_id,
                action_id=context.action_id,
                idempotency_key=idempotency_key(context),
                reason=str(arguments.get("reason", "Agent deleted file.")),
            ),
        )
        if bound is not None:
            return bound
        source = await service.delete_file(
            user_id=context.user_id,
            source_id=source_id,
            action_id=context.action_id,
            idempotency_key=idempotency_key(context),
            reason=str(arguments.get("reason", "Agent deleted file.")),
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "FILE_DELETED",
            "File deleted.",
            data={"file_id": str(source.id), "replayed": source.replayed},
        )

    for definition in (
        ToolDefinition(
            "file_search",
            "Search user files and matching fragments.",
            ToolRisk.READ,
            search_files,
            required_arguments=("query",),
        ),
        ToolDefinition(
            "file_inspect",
            "Inspect a file using its stable internal file_id.",
            ToolRisk.READ,
            inspect_file,
            required_arguments=("file_id",),
        ),
        ToolDefinition(
            "file_delete",
            "Delete a user file after confirmation.",
            ToolRisk.IRREVERSIBLE,
            delete_file,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("file_id",),
        ),
    ):
        registry.register(definition)


def register_search_tools(
    registry: ToolRegistry,
    service: SearchApplicationService | None,
    unit_of_work_factory: Callable[[], Any] | None = None,
) -> None:
    if service is None:
        return

    from laoshiren.application.files.observations import promote_url_inspection

    async def search_web(context: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        query = normalize_search_query(str(arguments["query"]))
        domains_raw = arguments.get("domains")
        domains: tuple[str, ...] | None = None
        if isinstance(domains_raw, list):
            domains = tuple(str(item) for item in domains_raw if str(item).strip())
        payload = await service.search_web(
            user_id=context.user_id,
            query=query,
            limit=int(arguments["limit"]) if arguments.get("limit") is not None else None,
            recency_days=(
                int(arguments["recency_days"])
                if arguments.get("recency_days") is not None
                else None
            ),
            domains=domains,
        )
        urls = tuple(
            str(item["url"])
            for item in payload.get("items", [])
            if isinstance(item, dict) and item.get("url")
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "OK",
            "Web search completed.",
            data=payload,
            source_refs=urls,
        )

    async def inspect_url(context: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        url = str(arguments["url"])
        payload = await service.inspect_url(
            user_id=context.user_id,
            url=url,
        )
        if bool(arguments.get("persist_observation")) and unit_of_work_factory is not None:
            async with unit_of_work_factory() as unit_of_work:
                observation_id = await promote_url_inspection(
                    unit_of_work,
                    user_id=context.user_id,
                    requested_url=url,
                    payload=payload,
                )
                await unit_of_work.commit()
            payload = {**payload, "web_observation_id": str(observation_id)}
            payload["evidence_ref"] = web_evidence_ref(observation_id).to_json()
        urls = tuple(
            str(item["url"])
            for item in payload.get("items", [])
            if isinstance(item, dict) and item.get("url")
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "OK",
            "URL inspected.",
            data=payload,
            source_refs=urls,
        )

    for definition in (
        ToolDefinition(
            "search_web",
            "Search the public web.",
            ToolRisk.READ,
            search_web,
            required_arguments=("query",),
        ),
        ToolDefinition(
            "url_inspect",
            "Inspect a known URL resource.",
            ToolRisk.READ,
            inspect_url,
            required_arguments=("url",),
        ),
    ):
        registry.register(definition)


def build_tool_manifest(registry: ToolRegistry) -> str:
    """Render concise tool descriptions from the registry for the model prompt."""
    lines: list[str] = []
    for name in registry.names():
        definition = registry.get(name)
        if definition is None:
            continue
        arguments = ", ".join(definition.required_arguments)
        suffix = f"；参数：{arguments}" if arguments else ""
        lines.append(f"{name}：{definition.description}{suffix}")
    return "\n".join(lines)


def export_tool_registry_contract(registry: ToolRegistry) -> list[dict[str, Any]]:
    """Serialize the registered V2.2 tool surface for contract drift checks."""
    contract: list[dict[str, Any]] = []
    for name in registry.names():
        definition = registry.get(name)
        if definition is None:
            continue
        contract.append(
            {
                "name": name,
                "description": definition.description,
                "risk": definition.risk.value,
                "replay_policy": definition.replay_policy.value,
                "required_arguments": list(definition.required_arguments),
            }
        )
    return contract
