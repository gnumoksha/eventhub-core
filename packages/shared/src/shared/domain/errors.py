class DomainError(Exception):
    """Base class for errors raised by the domain."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EntityNotFound(DomainError):
    """An entity was not found."""


class InvalidValue(DomainError):
    """A value does not satisfy the domain rules (e.g. an empty title)."""


class InvalidStateTransition(DomainError):
    """The operation is not allowed in the current state of the aggregate."""


class ConcurrencyConflict(DomainError):
    """The aggregate was modified by someone else since it was loaded."""


class AccessDenied(DomainError):
    """Access to the entity is denied."""
