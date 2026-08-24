from laoshiren.application.automations.service import AutomationApplicationService


async def run_once(service: AutomationApplicationService, *, limit: int = 100) -> tuple[int, int]:
    generated = await service.process_due(limit=limit)
    submitted = await service.dispatch_pending(limit=limit)
    return generated, submitted
