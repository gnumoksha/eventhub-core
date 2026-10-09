from shared.domain.errors import DomainError


class InvalidValue(DomainError):
    """A value does not satisfy the domain rules (e.g. an empty title)."""


class InvalidStateTransition(DomainError):
    """The operation is not allowed in the current state of the aggregate."""


class ConcurrencyConflict(DomainError):
    """The aggregate was modified by someone else since it was loaded."""
