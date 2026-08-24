from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from laoshiren.agent.graph import build_executive_graph
from laoshiren.agent.model_gateway import ExecutiveModelGateway
from laoshiren.agent.tools import ToolRegistry, register_personal_state_tools
from laoshiren.application.automations.service import (
    AttentionApplicationService,
    AutomationApplicationService,
)
from laoshiren.application.memories.context import (
    AgentMemoryApplicationService,
    EmbeddingProvider,
)
from laoshiren.application.memories.service import MemoryApplicationService
from laoshiren.application.personal_state.service import PersonalStateApplicationService
from laoshiren.application.runtime.service import RuntimeApplicationService
from laoshiren.application.sources.service import SourceApplicationService
from laoshiren.application.system.service import OperationalStatusApplicationService
from laoshiren.config.settings import Settings, get_settings
from laoshiren.infrastructure.ai.deepseek import DeepSeekExecutiveModelGateway
from laoshiren.infrastructure.ai.embeddings import OpenAICompatibleEmbeddingProvider
from laoshiren.infrastructure.ai.zhipu import ZhipuExecutiveModelGateway
from laoshiren.infrastructure.notifications.recording import RecordingNotificationAdapter
from laoshiren.infrastructure.persistence.checkpoints import PostgresCheckpointLifecycle
from laoshiren.infrastructure.persistence.database import Database
from laoshiren.infrastructure.persistence.operational_status import (
    SqlAlchemyOperationalStatusAdapter,
)
from laoshiren.infrastructure.runtime.dispatcher import InProcessRunDispatcher
from laoshiren.infrastructure.sources.text_parser import TextSourceParser
from laoshiren.infrastructure.storage.local import LocalObjectStorage
from laoshiren.workers.agent import (
    AgentRunWorker,
    RuntimeAgentEventSink,
    RuntimeToolExecutionLedger,
)
from laoshiren.workers.automation import AutomationScheduler
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
    run_dispatcher: InProcessRunDispatcher
    run_scanner: RunDispatchScanner
    source_scheduler: SourceProcessingScheduler
    automation_scheduler: AutomationScheduler


def bootstrap() -> Container:
    settings = get_settings()
    database = Database(settings.database_url)
    personal_state = PersonalStateApplicationService(database.personal_state_unit_of_work)
    storage = LocalObjectStorage(Path(settings.object_storage_path))
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
    memories = MemoryApplicationService(database.memory_unit_of_work)
    embedding_provider: EmbeddingProvider | None = None
    if (
        settings.embedding_model_name
        and settings.embedding_api_base
        and settings.embedding_api_key
    ):
        if settings.embedding_dimensions != 1536:
            raise ValueError("Embedding dimensions must match the pgvector schema (1536).")
        embedding_provider = OpenAICompatibleEmbeddingProvider(
            api_key=settings.embedding_api_key,
            model=settings.embedding_model_name,
            api_base=settings.embedding_api_base,
            dimensions=settings.embedding_dimensions,
            timeout_seconds=settings.embedding_timeout_seconds,
        )
    notification_adapter = RecordingNotificationAdapter()
    automations = AutomationApplicationService(
        database.automation_unit_of_work, notification_adapter
    )
    attention = AttentionApplicationService(database.automation_unit_of_work)
    operational_status = OperationalStatusApplicationService(
        SqlAlchemyOperationalStatusAdapter(database.session_factory)
    )
    run_dispatcher = InProcessRunDispatcher()
    runtime = RuntimeApplicationService(database.runtime_unit_of_work, run_dispatcher)
    run_scanner = RunDispatchScanner(
        runtime,
        interval_seconds=settings.run_scan_seconds,
        batch_size=settings.run_scan_batch_size,
    )
    checkpoints = PostgresCheckpointLifecycle(settings.database_url)
    automation_scheduler = AutomationScheduler(
        automations, interval_seconds=settings.automation_poll_seconds
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
        run_dispatcher=run_dispatcher,
        run_scanner=run_scanner,
        source_scheduler=source_scheduler,
        automation_scheduler=automation_scheduler,
    )


def build_agent_worker(
    container: Container, model_gateway: ExecutiveModelGateway
) -> AgentRunWorker:
    """Compose the Agent adapter only after the async checkpoint lifecycle has started."""
    tools = ToolRegistry()
    register_personal_state_tools(tools, container.personal_state)
    worker_id = f"agent-worker-{uuid4()}"
    graph = build_executive_graph(
        model_gateway=model_gateway,
        tools=tools,
        checkpointer=container.checkpoints.saver,
        event_sink=RuntimeAgentEventSink(container.runtime),
        tool_ledger=RuntimeToolExecutionLedger(
            container.runtime,
            owner=worker_id,
            lease_seconds=container.settings.run_lease_seconds,
        ),
    )
    return AgentRunWorker(
        container.runtime,
        graph,
        AgentMemoryApplicationService(
            container.memories, embedding_provider=container.embedding_provider
        ),
        container.sources,
        worker_id=worker_id,
        lease_seconds=container.settings.run_lease_seconds,
        heartbeat_seconds=container.settings.run_heartbeat_seconds,
    )


def build_configured_agent_worker(container: Container) -> AgentRunWorker:
    settings = container.settings
    provider = settings.model_provider.lower()
    if provider == "deepseek":
        gateway: ExecutiveModelGateway = DeepSeekExecutiveModelGateway(
            api_key=settings.model_api_key,
            model=settings.model_name,
            api_base=settings.model_api_base,
            timeout_seconds=settings.model_timeout_seconds,
        )
    elif provider == "zhipu":
        gateway = ZhipuExecutiveModelGateway(
            api_key=settings.model_api_key,
            model=settings.model_name,
            api_base=settings.model_api_base,
            timeout_seconds=settings.model_timeout_seconds,
        )
    else:
        raise RuntimeError("MODEL_PROVIDER must be configured as deepseek or zhipu.")
    return build_agent_worker(container, gateway)
