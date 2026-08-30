from enum import StrEnum


class OccurrenceStatus(StrEnum):
    MATERIALIZED = "MATERIALIZED"
    SUCCEEDED = "SUCCEEDED"
    NOT_MET = "NOT_MET"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


class NotificationKind(StrEnum):
    REMINDER = "REMINDER"
    CONDITION_MET = "CONDITION_MET"
    CONDITION_WATCH_ENDED = "CONDITION_WATCH_ENDED"


class DeliveryStatus(StrEnum):
    READY = "READY"
    ACCEPTED = "ACCEPTED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    CANCELLED = "CANCELLED"


class MisfirePolicy(StrEnum):
    FIRE_ONCE = "FIRE_ONCE"
    SKIP = "SKIP"


def is_one_shot_type(automation_type: str) -> bool:
    return automation_type in {"ONE_SHOT", "ONCE"}
