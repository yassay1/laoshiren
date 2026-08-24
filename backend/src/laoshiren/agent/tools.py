from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from laoshiren.agent.contracts import ToolResult, ToolStatus
from laoshiren.application.personal_state.service import PersonalStateApplicationService
from laoshiren.domain.personal_state.exceptions import (
    EntityNotFound,
    InvalidStateTransition,
    VersionConflict,
)
from laoshiren.domain.personal_state.value_objects import DateCertainty, DatePrecision

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
    ):
        registry.register(definition)
