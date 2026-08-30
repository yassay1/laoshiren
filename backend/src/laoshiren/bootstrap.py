from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from laoshiren.agent.contracts import GraphState
from laoshiren.agent.graph import build_executive_graph
from laoshiren.agent.model_gateway import ExecutiveModelGateway
from laoshiren.agent.policy import ToolPolicy
from laoshiren.agent.tools import (
    ToolRegistry,
    register_automation_tools,
    register_memory_tools,
    register_personal_state_tools,
    register_search_tools,
    register_source_tools,
)
from laoshiren.application.ai.ports import EmbeddingProvider
from laoshiren.application.automations.service import (
    AttentionApplicationService,
    AutomationApplicationService,
)
from laoshiren.application.context import AgentContextBuilder
from laoshiren.application.files.attachments import load_message_attachment_context
from laoshiren.application.identity.service import IdentityApplicationService
from laoshiren.application.memories.context import AgentMemoryApplicationService
from laoshiren.application.memories.manager import MemoryManager
from laoshiren.application.memories.service import MemoryApplicationService
from laoshiren.application.personal_state.service import PersonalStateApplicationService
from laoshiren.application.runtime.dto import (
    ContextAssemblyDTO,
    ContextAssemblyRequestDTO,
)
from laoshiren.application.runtime.service import RuntimeApplicationService
from laoshiren.application.search.service import SearchApplicationService
from laoshiren.application.sources.service import SourceApplicationService
from laoshiren.application.system.service import OperationalStatusApplicationService
from laoshiren.config.settings import Settings, get_settings
from laoshiren.domain.automations.entities import AttentionFeedbackAction
from laoshiren.infrastructure.ai.deepseek import DeepSeekExecutiveModelGateway
from laoshiren.infrastructure.ai.embeddings import OpenAICompatibleEmbeddingProvider
from laoshiren.infrastructure.ai.memory_extractor import OpenAIMemoryExtractor
from laoshiren.infrastructure.ai.retrying import (
    FailoverExecutiveModelGateway,
    RetryingExecutiveModelGateway,
)
from laoshiren.infrastructure.ai.zhipu import ZhipuExecutiveModelGateway
from laoshiren.infrastructure.automation.run_trigger import RuntimeAutomationRunTrigger
from laoshiren.infrastructure.coordination.checkpoint_inspector import (
    LangGraphCheckpointInspector,
)
from laoshiren.infrastructure.coordination.redis_wakeup import RedisRuntimeWakeup
from laoshiren.infrastructure.notifications.recording import RecordingNotificationAdapter
from laoshiren.infrastructure.persistence.checkpoints import PostgresCheckpointLifecycle
from laoshiren.infrastructure.persistence.database import Database
from laoshiren.infrastructure.persistence.operational_status import (
    SqlAlchemyOperationalStatusAdapter,
)
from laoshiren.infrastructure.search.factory import build_web_search_port
from laoshiren.infrastructure.sources.text_parser import TextSourceParser
from laoshiren.infrastructure.storage.local import LocalObjectStorage
from laoshiren.workers.account_deletion import AccountDeletionScheduler, AccountDeletionWorker
from laoshiren.workers.agent import (
    AgentRunWorker,
    RuntimeAgentEventSink,
    RuntimeToolExecutionLedger,
)
from laoshiren.workers.automation import AutomationScheduler
from laoshiren.workers.automation_occurrence import AutomationOccurrenceWorker
from laoshiren.workers.file_purge import FilePurgeScheduler, FilePurgeWorker
from laoshiren.workers.memory import MemoryFormationWorker
from laoshiren.workers.push_delivery import PushDeliveryWorker
from laoshiren.workers.runtime import RunDispatchScanner
from laoshiren.workers.source import SourceProcessingScheduler, SourceProcessingWorker


@dataclass(frozen=True, slots=True)
class Container:
    """Composition root result; dependencies are added here as layers land."""

    settings: Settings
    database: Database
    personal_state: PersonalStateApplicationService
    sources: SourceApplicationService
    memories: MemoryApplicationService
    embedding_provider: EmbeddingProvider | None
    automations: AutomationApplicationService
    attention: AttentionApplicationService
    operational_status: OperationalStatusApplicationService
    runtime: RuntimeApplicationService
    notification_adapter: RecordingNotificationAdapter
    checkpoints: PostgresCheckpointLifecycle
    run_scanner: RunDispatchScanner
    source_scheduler: SourceProcessingScheduler
    file_purge_scheduler: FilePurgeScheduler
    automation_scheduler: AutomationScheduler
    memory_manager: MemoryManager | None
    memory_formation: MemoryFormationWorker | None
    runtime_wakeup: RedisRuntimeWakeup
    identity: IdentityApplicationService
    account_deletion_scheduler: AccountDeletionScheduler


def bootstrap() -> Container:
    settings = get_settings()
    database = Database(settings.database_url)
    personal_state = PersonalStateApplicationService(database.personal_state_unit_of_work)
    storage = LocalObjectStorage(Path(settings.object_storage_path))
    embedding_provider: EmbeddingProvider | None = None
    if settings.embedding_model_name and settings.embedding_api_base and settings.embedding_api_key:
        if settings.embedding_dimensions != 1536:
            raise ValueError("Embedding dimensions must match the pgvector schema (1536).")
        embedding_provider = OpenAICompatibleEmbeddingProvider(
            api_key=settings.embedding_api_key,
            model=settings.embedding_model_name,
            api_base=settings.embedding_api_base,
            dimensions=settings.embedding_dimensions,
            timeout_seconds=settings.embedding_timeout_seconds,
        )
    sources = SourceApplicationService(
        database.personal_state_unit_of_work,
        storage,
        max_upload_bytes=settings.max_upload_bytes,
        parser=TextSourceParser(
            max_extracted_characters=settings.source_max_extracted_characters,
            max_pdf_pages=settings.source_max_pdf_pages,
            max_pdf_page_characters=settings.source_max_pdf_page_characters,
        ),
        parse_timeout_seconds=settings.source_parse_timeout_seconds,
        embedding_provider=embedding_provider,
        embedding_model_version=settings.embedding_model_name or None,
    )
    source_worker = SourceProcessingWorker(
        sources,
        lease_seconds=settings.source_lease_seconds,
        heartbeat_seconds=settings.source_heartbeat_seconds,
        max_attempts=settings.source_max_attempts,
        retry_base_seconds=settings.source_retry_base_seconds,
        retry_max_seconds=settings.source_retry_max_seconds,
    )
    source_scheduler = SourceProcessingScheduler(
        source_worker,
        interval_seconds=settings.source_poll_seconds,
        batch_size=settings.source_batch_size,
    )
    file_purge_worker = FilePurgeWorker(
        database.personal_state_unit_of_work,
        storage,
        lease_seconds=settings.source_lease_seconds,
    )
    file_purge_scheduler = FilePurgeScheduler(
        file_purge_worker,
        interval_seconds=settings.source_poll_seconds,
        batch_size=settings.source_batch_size,
    )
    account_deletion_worker = AccountDeletionWorker(
        database.personal_state_unit_of_work,
        lease_seconds=settings.source_lease_seconds,
    )
    account_deletion_scheduler = AccountDeletionScheduler(
        account_deletion_worker,
        interval_seconds=settings.source_poll_seconds,
        batch_size=settings.source_batch_size,
    )
    identity = IdentityApplicationService(
        database.personal_state_unit_of_work,
        app_env=settings.app_env,
        session_ttl_hours=settings.session_ttl_hours,
    )
    memories = MemoryApplicationService(database.memory_unit_of_work)
    notification_adapter = RecordingNotificationAdapter()
    attention = AttentionApplicationService(database.automation_unit_of_work)
    operational_status = OperationalStatusApplicationService(
        SqlAlchemyOperationalStatusAdapter(database.session_factory)
    )
    runtime_wakeup = RedisRuntimeWakeup(settings.redis_url, enabled=settings.redis_wakeup_enabled)
    runtime = RuntimeApplicationService(
        database.runtime_unit_of_work,
        wakeup=runtime_wakeup,
        budget_snapshot={
            "max_model_steps": settings.runtime_max_model_steps,
            "max_tool_actions": settings.runtime_max_tool_actions,
            "max_input_tokens": settings.runtime_max_input_tokens,
            "max_output_tokens": settings.runtime_max_output_tokens,
            "max_external_actions": settings.runtime_max_external_actions,
            "max_search_queries": settings.search_max_queries_per_run,
            "max_active_wall_time_seconds": settings.runtime_max_active_wall_time_seconds,
        },
    )
    run_trigger = RuntimeAutomationRunTrigger(runtime)
    automations = AutomationApplicationService(
        database.automation_unit_of_work,
        notification_adapter,
        run_trigger=run_trigger,
    )
    run_scanner = RunDispatchScanner(
        runtime,
        interval_seconds=settings.run_scan_seconds,
        batch_size=settings.run_scan_batch_size,
        lease_seconds=settings.run_lease_seconds,
    )
    checkpoints = PostgresCheckpointLifecycle(settings.database_url)
    automation_occurrence_worker = AutomationOccurrenceWorker(
        database.automation_unit_of_work,
        run_trigger=run_trigger,
    )
    push_delivery_worker = PushDeliveryWorker(
        database.automation_unit_of_work,
        notification_adapter,
    )
    automation_scheduler = AutomationScheduler(
        automations,
        automation_occurrence_worker,
        push_delivery_worker,
        interval_seconds=settings.automation_poll_seconds,
    )
    memory_manager: MemoryManager | None = None
    memory_formation: MemoryFormationWorker | None = None
    if settings.model_api_key:
        extractor = OpenAIMemoryExtractor(
            api_key=settings.model_api_key,
            model=settings.model_name,
            api_base=settings.model_api_base,
            timeout_seconds=settings.model_timeout_seconds,
        )
        memory_manager = MemoryManager(memories, extractor, embedding_provider=embedding_provider)
        memory_formation = MemoryFormationWorker(
            memory_manager,
            runtime,
            database.personal_state_unit_of_work,
        )
    return Container(
        settings=settings,
        database=database,
        personal_state=personal_state,
        sources=sources,
        memories=memories,
        embedding_provider=embedding_provider,
        automations=automations,
        attention=attention,
        operational_status=operational_status,
        runtime=runtime,
        notification_adapter=notification_adapter,
        checkpoints=checkpoints,
        run_scanner=run_scanner,
        source_scheduler=source_scheduler,
        file_purge_scheduler=file_purge_scheduler,
        automation_scheduler=automation_scheduler,
        memory_manager=memory_manager,
        memory_formation=memory_formation,
        runtime_wakeup=runtime_wakeup,
        identity=identity,
        account_deletion_scheduler=account_deletion_scheduler,
    )


def build_agent_worker(
    container: Container, model_gateway: ExecutiveModelGateway
) -> AgentRunWorker:
    """Compose the Agent adapter only after the async checkpoint lifecycle has started."""
    tools = ToolRegistry()
    register_personal_state_tools(tools, container.personal_state, container.runtime)
    register_automation_tools(tools, container.automations, container.runtime)
    register_source_tools(tools, container.sources, container.runtime)
    agent_memory = AgentMemoryApplicationService(
        container.memories, embedding_provider=container.embedding_provider
    )
    register_memory_tools(tools, agent_memory, container.memory_manager, container.runtime)
    search_service = SearchApplicationService(
        build_web_search_port(container.settings),
        default_limit=container.settings.search_default_limit,
        max_snippet_characters=container.settings.search_max_snippet_characters,
        cache_ttl_seconds=container.settings.search_cache_ttl_seconds,
    )
    register_search_tools(tools, search_service, container.database.personal_state_unit_of_work)
    invocation_context_builder = AgentContextBuilder()

    async def refresh_context(state: GraphState) -> GraphState:
        user_id = UUID(state["user_id"])
        thread_id = UUID(state["thread_id"])
        query = state.get("current_input", "")
        messages = await container.runtime.list_messages(
            user_id=user_id, thread_id=thread_id, limit=500
        )
        memory = (await agent_memory.load_context(user_id=user_id, query=query)).as_prompt_data()
        thread = await container.runtime.get_thread(user_id=user_id, thread_id=thread_id)
        overview = await container.personal_state.get_state_overview(user_id=user_id)
        active = await container.personal_state.get_agent_thing_prefetch(
            user_id=user_id,
            active_thing_id=thread.active_thing_id,
            query=query,
        )
        # Sources are invocation-time context too.  A Tool or an external
        # processor may have changed their extracted/chunked representation
        # since the previous model step.
        source_context: list[dict[str, str]] = []
        remaining = 12_000
        raw_source_refs = state.get("source_refs", [])
        source_refs = raw_source_refs if isinstance(raw_source_refs, list) else []
        for raw_source_id in source_refs:
            if remaining <= 0:
                break
            source_id = UUID(raw_source_id)
            source = await container.sources.get(user_id=user_id, source_id=source_id)
            chunks = await container.sources.get_context_chunks(
                user_id=user_id,
                source_id=source_id,
                max_chunks=8,
                max_characters=remaining,
                query=query,
            )
            for chunk in chunks:
                if remaining <= 0:
                    break
                content = chunk.content[:remaining]
                source_context.append(
                    {
                        "source_id": str(source.id),
                        "chunk_id": str(chunk.id),
                        "ordinal": str(chunk.ordinal),
                        "page_number": (
                            str(chunk.page_number) if chunk.page_number is not None else ""
                        ),
                        "title": source.title,
                        "content": content,
                    }
                )
                remaining -= len(content)
            if not chunks and source.extracted_text and remaining > 0:
                content = source.extracted_text[:remaining]
                source_context.append(
                    {
                        "source_id": str(source.id),
                        "chunk_id": "",
                        "ordinal": "0",
                        "title": source.title,
                        "content": content,
                    }
                )
                remaining -= len(content)
        attachment_context: list[dict[str, str]] = []
        raw_input_message_id = state.get("input_message_id")
        if raw_input_message_id:
            async with container.database.personal_state_unit_of_work() as unit_of_work:
                attachment_context = await load_message_attachment_context(
                    unit_of_work,
                    user_id=user_id,
                    message_id=UUID(str(raw_input_message_id)),
                )
                await unit_of_work.rollback()
        attention = tuple(await container.attention.get_candidates(user_id=user_id, limit=5))
        bounded = invocation_context_builder.build(
            messages=messages,
            memory_context=memory,
            source_context=source_context,
            attachment_context=attachment_context,
            state_overview=overview,
            active_thing_context=active,
            attention=attention,
        )
        prefetched = bounded.prefetched_state
        # Only mark the candidates that survived bounded assembly as surfaced;
        # this stays invocation-time and never writes a stale prefetch snapshot
        # into the checkpoint.
        for candidate in attention[:3]:
            await container.attention.record_feedback(
                user_id=user_id,
                subject_type=candidate.subject_type,
                subject_id=candidate.subject_id,
                action=AttentionFeedbackAction.SURFACED,
                dismissed_until=None,
            )
        raw_memory_profile = memory.get("profile", [])
        raw_memory_relevant = memory.get("relevant", [])
        memory_groups = tuple(
            group for group in (raw_memory_profile, raw_memory_relevant) if isinstance(group, list)
        )
        raw_active_items = active.get("things", []) if isinstance(active, dict) else []
        active_items = raw_active_items if isinstance(raw_active_items, list) else []
        included = {
            "message_ids": [str(item["id"]) for item in bounded.messages],
            "source_ids": sorted(
                {str(item.get("source_id")) for item in source_context if item.get("source_id")}
            ),
            "file_ids": sorted(
                {str(item.get("file_id")) for item in attachment_context if item.get("file_id")}
            ),
            "memory_ids": sorted(
                {
                    str(item.get("id"))
                    for group in memory_groups
                    for item in group
                    if isinstance(item, dict) and item.get("id")
                }
            ),
            "thing_ids": sorted(
                {
                    str(item.get("thing_id"))
                    for item in active_items
                    if isinstance(item, dict) and item.get("thing_id")
                }
            ),
        }
        return {
            "messages": bounded.messages,
            "prefetched_state": prefetched,
            "context_manifest": {
                "model_invocation_id": str(uuid4()),
                "run_id": state["run_id"],
                "current_message_id": (
                    str(run_input_id) if (run_input_id := state.get("input_message_id")) else None
                ),
                "included": included,
                "token_estimate": len(str(prefetched)),
                "source_refs": list(state.get("source_refs", [])),
                "state_authority": "PERSONAL_STATE",
                "decision_index": state.get("decision_count", 0),
            },
        }

    class BootstrapModelContextAssembler:
        """Composition-root adapter from stable references to fresh context."""

        async def assemble(self, *, request: ContextAssemblyRequestDTO) -> ContextAssemblyDTO:
            refreshed = await refresh_context(
                {
                    "user_id": str(request.user_id),
                    "thread_id": str(request.thread_id),
                    "run_id": str(request.run_id),
                    "input_message_id": (
                        str(request.input_message_id)
                        if request.input_message_id is not None
                        else ""
                    ),
                    "current_input": request.current_input,
                    "source_refs": [str(value) for value in request.source_refs],
                    "decision_count": request.decision_index,
                }
            )
            return ContextAssemblyDTO(
                messages=cast(list[dict[str, object]], refreshed["messages"]),
                prefetched_state=cast(dict[str, object], refreshed["prefetched_state"]),
                context_manifest=cast(dict[str, object], refreshed["context_manifest"]),
            )

    worker_id = f"agent-worker-{uuid4()}"
    graph = build_executive_graph(
        model_gateway=model_gateway,
        tools=tools,
        checkpointer=container.checkpoints.saver,
        event_sink=RuntimeAgentEventSink(container.runtime),
        policy_matrix=ToolPolicy(search_max_per_run=container.settings.search_max_queries_per_run),
        parallel_read_max=container.settings.parallel_read_max,
        search_max_per_run=container.settings.search_max_queries_per_run,
        tool_ledger=RuntimeToolExecutionLedger(
            container.runtime,
            owner=worker_id,
            lease_seconds=container.settings.run_lease_seconds,
        ),
        max_decisions=container.settings.runtime_max_model_steps,
        max_tool_calls=container.settings.runtime_max_tool_actions,
        max_input_tokens=container.settings.runtime_max_input_tokens,
        max_output_tokens=container.settings.runtime_max_output_tokens,
        max_external_actions=container.settings.runtime_max_external_actions,
        context_assembler=BootstrapModelContextAssembler(),
    )
    return AgentRunWorker(
        container.runtime,
        graph,
        memory_formation=container.memory_formation,
        worker_id=worker_id,
        lease_seconds=container.settings.run_lease_seconds,
        heartbeat_seconds=container.settings.run_heartbeat_seconds,
        max_active_wall_time_seconds=(container.settings.runtime_max_active_wall_time_seconds),
        checkpoint_inspector=LangGraphCheckpointInspector(graph),
    )


def build_configured_agent_worker(container: Container) -> AgentRunWorker:
    settings = container.settings

    def build_gateway(
        provider: str, *, api_key: str, model: str, api_base: str
    ) -> ExecutiveModelGateway:
        if provider == "deepseek":
            return DeepSeekExecutiveModelGateway(
                api_key=api_key,
                model=model,
                api_base=api_base,
                timeout_seconds=settings.model_timeout_seconds,
            )
        if provider == "zhipu":
            return ZhipuExecutiveModelGateway(
                api_key=api_key,
                model=model,
                api_base=api_base,
                timeout_seconds=settings.model_timeout_seconds,
            )
        raise RuntimeError("MODEL_PROVIDER must be configured as deepseek or zhipu.")

    gateway = build_gateway(
        settings.model_provider.lower(),
        api_key=settings.model_api_key,
        model=settings.model_name,
        api_base=settings.model_api_base,
    )
    fallback_provider = settings.model_fallback_provider.lower().strip()
    if fallback_provider:
        fallback = build_gateway(
            fallback_provider,
            api_key=settings.model_fallback_api_key,
            model=settings.model_fallback_name or settings.model_name,
            api_base=settings.model_fallback_api_base or settings.model_api_base,
        )
        gateway = FailoverExecutiveModelGateway(gateway, fallback)
    return build_agent_worker(
        container,
        RetryingExecutiveModelGateway(
            gateway,
            max_attempts=settings.model_retry_attempts,
            base_seconds=settings.model_retry_base_seconds,
        ),
    )
