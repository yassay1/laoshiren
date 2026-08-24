class DomainError(Exception):
    """Base exception for deterministic business rule violations."""


class InvalidStateTransition(DomainError):
    """Raised when an entity cannot move to the requested state."""


class EntityNotFound(DomainError):
    """Raised when a requested domain entity does not exist for the user."""


class VersionConflict(DomainError):
    """Raised when optimistic concurrency detects a stale write."""
