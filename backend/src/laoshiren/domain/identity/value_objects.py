from enum import StrEnum


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DELETING = "DELETING"
    DELETED = "DELETED"


class DevicePlatform(StrEnum):
    HARMONYOS = "HARMONYOS"
    OTHER = "OTHER"
