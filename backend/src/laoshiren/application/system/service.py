from dataclasses import dataclass
from datetime import UTC, datetime

from laoshiren.application.system.ports import OperationalStatusPort


@dataclass(frozen=True, slots=True)
class OperationalStatusDTO:
    status: str
    checked_at: datetime
    backlogs: dict[str, int]


class OperationalStatusApplicationService:
    def __init__(self, port: OperationalStatusPort) -> None:
        self._port = port

    async def get_status(self) -> OperationalStatusDTO:
        now = datetime.now(UTC)
        backlogs = await self._port.count_backlogs(now=now)
        return OperationalStatusDTO(status="ready", checked_at=now, backlogs=backlogs)
