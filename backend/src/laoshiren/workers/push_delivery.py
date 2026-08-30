"""Worker that delivers PUSH_DELIVERY durable jobs."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from laoshiren.application.automations.notification_pipeline import push_delivery_dedupe_key
from laoshiren.application.automations.ports import AutomationUnitOfWork, PushNotificationPort
from laoshiren.application.runtime.durable_job_claim import claim_ready_jobs
from laoshiren.domain.runtime.entities import DurableJobKind, DurableJobStatus

UnitOfWorkFactory = Callable[[], AutomationUnitOfWork]


class PushDeliveryWorker:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        notification_port: PushNotificationPort,
        *,
        worker_id: str | None = None,
        lease_seconds: float = 60.0,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("Push delivery lease must be positive.")
        self._unit_of_work_factory = unit_of_work_factory
        self._notification_port = notification_port
        self._worker_id = worker_id or f"push-delivery-{uuid4()}"
        self._lease_seconds = lease_seconds

    async def run_once(self) -> bool:
        now = datetime.now(UTC)
        async with self._unit_of_work_factory() as unit_of_work:
            jobs = await claim_ready_jobs(
                unit_of_work,
                kind=DurableJobKind.PUSH_DELIVERY,
                owner=self._worker_id,
                now=now,
                lease_until=now + timedelta(seconds=self._lease_seconds),
                limit=1,
            )
            if not jobs:
                await unit_of_work.rollback()
                return False
            job = jobs[0]
            await unit_of_work.commit()

        delivery_id = UUID(str(job.payload["delivery_id"]))
        intent_id = UUID(str(job.payload["intent_id"]))
        endpoint_id = UUID(str(job.payload["endpoint_id"]))
        async with self._unit_of_work_factory() as unit_of_work:
            delivery = await unit_of_work.notification_deliveries.get(delivery_id=delivery_id)
            intent = await unit_of_work.notification_intents.get(intent_id=intent_id)
            endpoint = await unit_of_work.push_endpoints.get(endpoint_id=endpoint_id)
            if delivery is None or intent is None or endpoint is None:
                await unit_of_work.rollback()
            else:
                try:
                    accepted = await self._notification_port.submit_delivery(
                        delivery=delivery,
                        intent=intent,
                        endpoint=endpoint,
                        idempotency_key=push_delivery_dedupe_key(delivery.id),
                    )
                except Exception:
                    accepted = False
                if accepted:
                    delivery.accepted()
                else:
                    delivery.failed(error_code="ADAPTER_REJECTED")
                await unit_of_work.notification_deliveries.update(delivery)
                await unit_of_work.commit()

        async with self._unit_of_work_factory() as unit_of_work:
            settled = await unit_of_work.durable_jobs.settle(
                job_id=job.id,
                owner=self._worker_id,
                claim_epoch=job.claim_epoch,
                status=DurableJobStatus.COMPLETED,
                now=datetime.now(UTC),
            )
            if settled:
                await unit_of_work.commit()
            else:
                await unit_of_work.rollback()
        return True
