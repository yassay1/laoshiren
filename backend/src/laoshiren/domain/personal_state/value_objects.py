from enum import StrEnum


class ThingStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TaskStatus(StrEnum):
    TODO = "TODO"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class DateCertainty(StrEnum):
    CONFIRMED = "CONFIRMED"
    PROBABLE = "PROBABLE"
    UNCONFIRMED = "UNCONFIRMED"
    DISPUTED = "DISPUTED"


class DatePrecision(StrEnum):
    DATE_TIME = "DATE_TIME"
    DATE = "DATE"
    MONTH = "MONTH"


class ThingDateType(StrEnum):
    DEADLINE = "DEADLINE"
    EVENT = "EVENT"
    MILESTONE = "MILESTONE"


class BlockerStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class BlockerSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ThingRelationType(StrEnum):
    RELATED_TO = "RELATED_TO"
    DEPENDS_ON = "DEPENDS_ON"
    PART_OF = "PART_OF"
