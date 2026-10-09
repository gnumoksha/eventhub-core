class DomainError(Exception):
    """Base class for errors raised by the domain."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
