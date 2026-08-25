from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from laoshiren.agent.contracts import ToolResult, ToolStatus
from laoshiren.application.automations.service import AutomationApplicationService
from laoshiren.application.memories.context import AgentMemoryApplicationService
from laoshiren.application.personal_state.service import PersonalStateApplicationService
from laoshiren.domain.automations.entities import AutomationType
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
    ThingRelationType,
    ThingStatus,
)

ToolHandler = Callable[["ToolExecutionContext", dict[str, Any]], Awaitable[ToolResult]]


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


def register_personal_state_tools(
    registry: ToolRegistry, service: PersonalStateApplicationService
) -> None:
    async def get_thing(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        thing_id = UUID(str(arguments["thing_id"]))
        thing = await service.get_thing(user_id=context.user_id, thing_id=thing_id)
        return ToolResult(
            ToolStatus.SUCCESS,
            "OK",
            "Thing loaded.",
            data={
                "id": str(thing.id),
                "name": thing.name,
                "status": thing.status,
                "current_stage": thing.current_stage,
                "deadline_at": thing.deadline_at.isoformat() if thing.deadline_at else None,
                "version": thing.version,
            },
        )

    async def list_things(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        things = await service.get_things(
            user_id=context.user_id,
            query=str(arguments["query"]) if arguments.get("query") else None,
            limit=int(arguments.get("limit", 20)),
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "OK",
            "Things loaded.",
            data={
                "items": [
                    {
                        "id": str(thing.id),
                        "name": thing.name,
                        "status": thing.status,
                        "current_stage": thing.current_stage,
                        "deadline_at": (
                            thing.deadline_at.isoformat() if thing.deadline_at else None
                        ),
                        "version": thing.version,
                    }
                    for thing in things
                ]
            },
        )

    async def list_tasks(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        tasks = await service.get_tasks(
            user_id=context.user_id, thing_id=UUID(str(arguments["thing_id"]))
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "OK",
            "Tasks loaded.",
            data={
                "items": [
                    {
                        "id": str(task.id),
                        "thing_id": str(task.thing_id),
                        "title": task.title,
                        "status": task.status,
                        "version": task.version,
                    }
                    for task in tasks
                ]
            },
        )

    async def get_timeline(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        events = await service.get_timeline(
            user_id=context.user_id,
            thing_id=UUID(str(arguments["thing_id"])),
            limit=int(arguments.get("limit", 20)),
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "OK",
            "Timeline loaded.",
            data={
                "items": [
                    {
                        "id": str(event.id),
                        "event_type": event.event_type,
                        "title": event.title,
                        "occurred_at": event.occurred_at.isoformat(),
                    }
                    for event in events
                ]
            },
        )

    def idempotency_key(context: ToolExecutionContext) -> str:
        return context.idempotency_key

    async def create_thing(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
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

    async def create_task(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        task = await service.create_task(
            user_id=context.user_id,
            thing_id=UUID(str(arguments["thing_id"])),
            title=str(arguments["title"]),
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

    async def complete_task(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        result = await service.complete_task(
            user_id=context.user_id,
            task_id=UUID(str(arguments["task_id"])),
            expected_version=int(arguments["expected_version"]),
            action_id=context.action_id,
            idempotency_key=idempotency_key(context),
            reason=str(arguments.get("reason", "Agent completed Task")),
            run_id=context.run_id,
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "TASK_COMPLETED",
            "Task completed.",
            data={
                "mutation_id": str(result.mutation_id),
                "task_id": str(result.target_id),
                "version": result.target_version,
                "replayed": result.replayed,
            },
            mutation_refs=(str(result.mutation_id),),
        )

    async def set_deadline(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        result = await service.set_deadline(
            user_id=context.user_id,
            thing_id=UUID(str(arguments["thing_id"])),
            kind=str(arguments.get("kind", "DEADLINE")),
            value=datetime.fromisoformat(str(arguments["value"])),
            timezone_name=str(arguments["timezone"]),
            precision=DatePrecision(str(arguments.get("precision", "DATETIME"))),
            certainty=DateCertainty(str(arguments["certainty"])),
            is_primary=bool(arguments.get("is_primary", True)),
            expected_version=int(arguments["expected_version"]),
            action_id=context.action_id,
            idempotency_key=idempotency_key(context),
            reason=str(arguments.get("reason", "Agent set deadline")),
            run_id=context.run_id,
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

    async def get_blockers(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        blockers = await service.get_blockers(
            user_id=context.user_id, thing_id=UUID(str(arguments["thing_id"]))
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "OK",
            "Blockers loaded.",
            data={
                "items": [
                    {
                        "id": str(blocker.id),
                        "thing_id": str(blocker.thing_id),
                        "task_id": str(blocker.task_id) if blocker.task_id is not None else None,
                        "description": blocker.description,
                        "severity": blocker.severity.value,
                        "status": blocker.status.value,
                        "version": blocker.version,
                    }
                    for blocker in blockers
                ]
            },
        )

    async def get_dates(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        dates = await service.get_dates(
            user_id=context.user_id,
            thing_id=UUID(str(arguments["thing_id"])),
            limit=int(arguments.get("limit", 100)),
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "OK",
            "Dates loaded.",
            data={
                "items": [
                    {
                        "id": str(date.id),
                        "kind": date.kind,
                        "value": date.value.isoformat(),
                        "certainty": date.certainty.value,
                        "precision": date.precision.value,
                        "is_primary": date.is_primary,
                        "version": date.version,
                    }
                    for date in dates
                ]
            },
        )

    async def get_relations(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        relations = await service.get_relations(
            user_id=context.user_id, thing_id=UUID(str(arguments["thing_id"]))
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "OK",
            "Relations loaded.",
            data={
                "items": [
                    {
                        "from_thing_id": str(relation.from_thing_id),
                        "to_thing_id": str(relation.to_thing_id),
                        "relation_type": relation.relation_type.value,
                        "note": relation.note,
                    }
                    for relation in relations
                ]
            },
        )

    async def get_state_history(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        mutations = await service.get_state_history(
            user_id=context.user_id,
            thing_id=UUID(str(arguments["thing_id"])),
            limit=int(arguments.get("limit", 50)),
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "OK",
            "State history loaded.",
            data={
                "items": [
                    {
                        "id": str(mutation.id),
                        "mutation_type": mutation.mutation_type,
                        "before": mutation.before,
                        "after": mutation.after,
                        "reason": mutation.reason,
                        "created_at": mutation.created_at.isoformat(),
                    }
                    for mutation in mutations
                ]
            },
        )

    async def update_thing(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        thing = await service.update_thing(
            user_id=context.user_id,
            thing_id=UUID(str(arguments["thing_id"])),
            expected_version=int(arguments["expected_version"]),
            name=str(arguments["name"]) if arguments.get("name") else None,
            status=ThingStatus(str(arguments["status"])) if arguments.get("status") else None,
            current_stage=(
                str(arguments["current_stage"]) if arguments.get("current_stage") else None
            ),
            update_current_stage="current_stage" in arguments,
            action_id=context.action_id,
            idempotency_key=idempotency_key(context),
            reason=str(arguments.get("reason", "Agent updated Thing")),
            run_id=context.run_id,
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "THING_UPDATED",
            "Thing updated.",
            data={"id": str(thing.id), "version": thing.version},
        )

    async def transition_task(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
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

    async def add_relation(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        created = await service.add_relation(
            user_id=context.user_id,
            from_thing_id=UUID(str(arguments["from_thing_id"])),
            to_thing_id=UUID(str(arguments["to_thing_id"])),
            relation_type=ThingRelationType(str(arguments["relation_type"])),
            note=str(arguments["note"]) if arguments.get("note") else None,
            action_id=context.action_id,
            idempotency_key=idempotency_key(context),
            reason=str(arguments.get("reason", "Agent added Thing relation")),
        )
        return ToolResult(
            ToolStatus.SUCCESS,
            "RELATION_ADDED",
            "Thing relation added.",
            data={"created": created},
        )

    async def update_date(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
        result = await service.update_date(
            user_id=context.user_id,
            date_id=UUID(str(arguments["date_id"])),
            value=datetime.fromisoformat(str(arguments["value"])),
            timezone_name=str(arguments["timezone"]),
            precision=DatePrecision(str(arguments.get("precision", "DATETIME"))),
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

    async def archive_thing(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
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

    registry.register(
        ToolDefinition(
            name="state.get_thing",
            description="Read the current authoritative state of one Thing.",
            risk=ToolRisk.READ,
            handler=get_thing,
            required_arguments=("thing_id",),
        )
    )
    for definition in (
        ToolDefinition(
            "state.list_things", "List authoritative Things.", ToolRisk.READ, list_things
        ),
        ToolDefinition(
            "state.list_tasks",
            "List Tasks for a Thing.",
            ToolRisk.READ,
            list_tasks,
            required_arguments=("thing_id",),
        ),
        ToolDefinition(
            "state.get_timeline",
            "Read a Thing timeline.",
            ToolRisk.READ,
            get_timeline,
            required_arguments=("thing_id",),
        ),
        ToolDefinition(
            "state.create_thing",
            "Create a Thing.",
            ToolRisk.REVERSIBLE_WRITE,
            create_thing,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("name",),
        ),
        ToolDefinition(
            "state.create_task",
            "Create a Task.",
            ToolRisk.REVERSIBLE_WRITE,
            create_task,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("thing_id", "title"),
        ),
        ToolDefinition(
            "state.complete_task",
            "Complete a Task with optimistic concurrency.",
            ToolRisk.REVERSIBLE_WRITE,
            complete_task,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("task_id", "expected_version"),
        ),
        ToolDefinition(
            "state.set_deadline",
            "Set the formal deadline through the dedicated use case.",
            ToolRisk.SENSITIVE_WRITE,
            set_deadline,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=(
                "thing_id",
                "value",
                "timezone",
                "certainty",
                "expected_version",
            ),
        ),
        ToolDefinition(
            "state.get_blockers",
            "List the blockers of a Thing.",
            ToolRisk.READ,
            get_blockers,
            required_arguments=("thing_id",),
        ),
        ToolDefinition(
            "state.get_dates",
            "List the dates of a Thing.",
            ToolRisk.READ,
            get_dates,
            required_arguments=("thing_id",),
        ),
        ToolDefinition(
            "state.get_relations",
            "List the relations of a Thing.",
            ToolRisk.READ,
            get_relations,
            required_arguments=("thing_id",),
        ),
        ToolDefinition(
            "state.get_state_history",
            "Read a Thing's state mutation history.",
            ToolRisk.READ,
            get_state_history,
            required_arguments=("thing_id",),
        ),
        ToolDefinition(
            "state.update_thing",
            "Edit a Thing's name, status or stage.",
            ToolRisk.REVERSIBLE_WRITE,
            update_thing,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("thing_id", "expected_version"),
        ),
        ToolDefinition(
            "state.transition_task",
            "Transition a Task to another status.",
            ToolRisk.REVERSIBLE_WRITE,
            transition_task,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("task_id", "target_status", "expected_version"),
        ),
        ToolDefinition(
            "state.create_blocker",
            "Add a Blocker to a Thing.",
            ToolRisk.REVERSIBLE_WRITE,
            create_blocker,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("thing_id", "description"),
        ),
        ToolDefinition(
            "state.resolve_blocker",
            "Resolve a Blocker.",
            ToolRisk.REVERSIBLE_WRITE,
            resolve_blocker,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("blocker_id", "expected_version"),
        ),
        ToolDefinition(
            "state.add_relation",
            "Add a relation between two Things.",
            ToolRisk.REVERSIBLE_WRITE,
            add_relation,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("from_thing_id", "to_thing_id", "relation_type"),
        ),
        ToolDefinition(
            "state.update_date",
            "Update a Thing date.",
            ToolRisk.SENSITIVE_WRITE,
            update_date,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=(
                "date_id",
                "value",
                "timezone",
                "certainty",
                "expected_version",
                "expected_thing_version",
            ),
        ),
        ToolDefinition(
            "state.archive_thing",
            "Archive (soft-delete) a Thing.",
            ToolRisk.SENSITIVE_WRITE,
            archive_thing,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("thing_id", "expected_version"),
        ),
    ):
        registry.register(definition)


def register_automation_tools(
    registry: ToolRegistry, service: AutomationApplicationService
) -> None:
    def idempotency_key(context: ToolExecutionContext) -> str:
        return context.idempotency_key

    async def create_automation(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
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

    registry.register(
        ToolDefinition(
            "automation.create",
            "Create an automation (one-shot or recurring reminder).",
            ToolRisk.REVERSIBLE_WRITE,
            create_automation,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("automation_type", "title", "next_trigger_at"),
        )
    )
    registry.register(
        ToolDefinition(
            "automation.change",
            "Pause, resume or cancel an automation.",
            ToolRisk.REVERSIBLE_WRITE,
            change_automation,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            required_arguments=("automation_id", "action", "expected_version"),
        )
    )


def register_memory_tools(
    registry: ToolRegistry, memory: AgentMemoryApplicationService
) -> None:
    async def search(
        context: ToolExecutionContext, arguments: dict[str, Any]
    ) -> ToolResult:
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

    registry.register(
        ToolDefinition(
            "memory.search",
            "Search long-term memory by meaning.",
            ToolRisk.READ,
            search,
            required_arguments=("query",),
        )
    )


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
