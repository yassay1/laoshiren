from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID


class EvidenceSourceKind(StrEnum):
    MESSAGE = "MESSAGE"
    FILE = "FILE"
    WEB = "WEB"
    TOOL_RESULT = "TOOL_RESULT"


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    source_kind: EvidenceSourceKind
    source_id: UUID
    locator: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source_kind": self.source_kind.value,
            "source_id": str(self.source_id),
        }
        if self.locator:
            payload["locator"] = self.locator
        return payload

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "EvidenceRef":
        locator = data.get("locator")
        return cls(
            source_kind=EvidenceSourceKind(str(data["source_kind"])),
            source_id=UUID(str(data["source_id"])),
            locator=dict(locator) if isinstance(locator, dict) else None,
        )
