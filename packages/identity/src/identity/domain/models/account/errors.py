from shared.domain.errors import DomainError


class AuthenticationError(Exception):
    pass


class AccountNotFound(DomainError):
    pass


class InvalidCredentialToken(Exception):
    pass


class DuplicateAccountEmail(Exception):
    pass
