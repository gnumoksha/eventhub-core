from identity.application.authentication import (
    csrf_token,
    verify_csrf_token,
)
from shared.infra.authentication.token_encryption import decrypt_authentication_token, encrypt_authentication_token


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
