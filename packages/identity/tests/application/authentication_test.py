from fastapi import FastAPI
from fastapi.testclient import TestClient
from identity.application.authentication import (
    csrf_token,
    verify_csrf_token,
)
from identity.domain.models.values import Password
from identity.infra.http.authentication import require_trusted_origin
from identity.infra.http.routers.setup import setup_routers
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


def test_login_rejects_password_longer_than_maximum_length() -> None:
    app = FastAPI()
    setup_routers(app)
    app.dependency_overrides[require_trusted_origin] = lambda: None

    response = TestClient(app).post(
        "/identity/login",
        json={"email": "user@example.com", "password": "x" * (Password.MAX_LEN + 1)},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "string_too_long"
