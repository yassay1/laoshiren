from enum import StrEnum


class ThingStatus(StrEnum):
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    WAITING = "WAITING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ARCHIVED = "ARCHIVED"


class TaskStatus(StrEnum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class DateCertainty(StrEnum):
    CONFIRMED = "CONFIRMED"
    PROBABLE = "PROBABLE"
    UNCONFIRMED = "UNCONFIRMED"
    DISPUTED = "DISPUTED"


class DatePrecision(StrEnum):
    DATE = "DATE"
    DATETIME = "DATETIME"


class BlockerStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    IGNORED = "IGNORED"


class BlockerSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ThingRelationType(StrEnum):
    RELATED_TO = "RELATED_TO"
    DEPENDS_ON = "DEPENDS_ON"
    PART_OF = "PART_OF"
