from datetime import datetime
from typing import Protocol


class OperationalStatusPort(Protocol):
    async def count_backlogs(self, *, now: datetime) -> dict[str, int]: ...
