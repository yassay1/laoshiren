import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from laoshiren.bootstrap import bootstrap, build_configured_agent_worker
from laoshiren.config.asyncio_policy import configure_asyncio_policy
from laoshiren.domain.personal_state.exceptions import (
    EntityNotFound,
    InvalidStateTransition,
    VersionConflict,
)
from laoshiren.infrastructure.coordination.redis_rate_limit import RedisRateLimitMiddleware
from laoshiren.presentation.api.error_handlers import (
    entity_not_found_handler,
    http_exception_handler,
    invalid_state_transition_handler,
    request_validation_handler,
    value_error_handler,
    version_conflict_handler,
)
from laoshiren.presentation.api.routers.attention import router as attention_router
from laoshiren.presentation.api.routers.auth import router as auth_router
from laoshiren.presentation.api.routers.automations import router as automations_router
from laoshiren.presentation.api.routers.devices import router as devices_router
from laoshiren.presentation.api.routers.health import router as health_router
from laoshiren.presentation.api.routers.memories import router as memories_router
from laoshiren.presentation.api.routers.runtime import (
    runs_router,
    threads_router,
)
from laoshiren.presentation.api.routers.sources import router as sources_router
from laoshiren.presentation.api.routers.state import router as state_router
from laoshiren.presentation.api.routers.state_details import router as state_details_router
from laoshiren.presentation.api.routers.tasks import router as tasks_router
from laoshiren.presentation.api.routers.things import router as things_router
from laoshiren.presentation.api.routers.today import router as today_router

configure_asyncio_policy()
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    container = bootstrap()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await container.checkpoints.start()
        worker = build_configured_agent_worker(container)
        await container.run_scanner.start(worker.run_once)
        await container.source_scheduler.start()
        await container.file_purge_scheduler.start()
        await container.account_deletion_scheduler.start()
        await container.automation_scheduler.start()
        if container.memory_formation is not None:
            await container.memory_formation.start()
        try:
            yield
        finally:
            if container.memory_formation is not None:
                await container.memory_formation.stop()
            await container.automation_scheduler.stop()
            await container.account_deletion_scheduler.stop()
            await container.file_purge_scheduler.stop()
            await container.source_scheduler.stop()
            await container.run_scanner.stop()
            await container.checkpoints.stop()
            await container.runtime_wakeup.close()
            await container.database.dispose()

    app = FastAPI(title=container.settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.container = container
    app.add_middleware(
        RedisRateLimitMiddleware,
        redis_url=container.settings.redis_url,
        enabled=container.settings.rate_limit_enabled,
        requests_per_minute=container.settings.rate_limit_requests_per_minute,
    )

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_completed method=%s path=%s status=%s duration_ms=%.1f request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )
        return response

    app.include_router(health_router, prefix=container.settings.api_v1_prefix)
    app.include_router(auth_router, prefix=container.settings.api_v1_prefix)
    app.include_router(devices_router, prefix=container.settings.api_v1_prefix)
    app.include_router(things_router, prefix=container.settings.api_v1_prefix)
    app.include_router(tasks_router, prefix=container.settings.api_v1_prefix)
    app.include_router(sources_router, prefix=container.settings.api_v1_prefix)
    app.include_router(memories_router, prefix=container.settings.api_v1_prefix)
    app.include_router(state_details_router, prefix=container.settings.api_v1_prefix)
    app.include_router(state_router, prefix=container.settings.api_v1_prefix)
    app.include_router(today_router, prefix=container.settings.api_v1_prefix)
    app.include_router(automations_router, prefix=container.settings.api_v1_prefix)
    app.include_router(attention_router, prefix=container.settings.api_v1_prefix)
    app.include_router(threads_router, prefix=container.settings.api_v1_prefix)
    app.include_router(runs_router, prefix=container.settings.api_v1_prefix)
    app.add_exception_handler(EntityNotFound, entity_not_found_handler)
    app.add_exception_handler(VersionConflict, version_conflict_handler)
    app.add_exception_handler(InvalidStateTransition, invalid_state_transition_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(ValueError, value_error_handler)
    return app


app = create_app()
