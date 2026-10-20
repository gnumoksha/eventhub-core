import pytest
from identity.application.authentication import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    csrf_token,
    normalize_email,
    validate_password,
    verify_csrf_token,
)
from shared.infra.authentication.token_encryption import decrypt_authentication_token, encrypt_authentication_token


def test_normalize_email_trims_and_casefolds() -> None:
    assert normalize_email("  User.Name+tag@Example.COM ") == "user.name+tag@example.com"


@pytest.mark.parametrize("email", ["", "no-at-sign", "a@b", "a b@example.com", "a@@example.com"])
def test_normalize_email_rejects_invalid_addresses(email: str) -> None:
    with pytest.raises(ValueError):
        normalize_email(email)


def test_password_length_limits() -> None:
    validate_password("x" * PASSWORD_MIN_LENGTH)
    validate_password("x" * PASSWORD_MAX_LENGTH)

    with pytest.raises(ValueError):
        validate_password("x" * (PASSWORD_MIN_LENGTH - 1))
    with pytest.raises(ValueError):
        validate_password("x" * (PASSWORD_MAX_LENGTH + 1))


def test_csrf_token_is_bound_to_the_session_token() -> None:
    token = csrf_token("session-token", "application-secret")

    assert verify_csrf_token("session-token", "application-secret", token)
    assert not verify_csrf_token("another-session", "application-secret", token)
    assert not verify_csrf_token("session-token", "application-secret", None)


def test_email_credential_token_is_encrypted_before_delivery() -> None:
    raw_token = "one-time-authentication-token"
    encrypted = encrypt_authentication_token(raw_token)

    assert encrypted != raw_token
    assert decrypt_authentication_token(encrypted) == raw_token
