import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from identity.domain.models.account.account import Account, Session
from identity.domain.models.account.errors import (
    AuthenticationError,
    DuplicateAccountEmail,
    InvalidCredentialToken,
)
from identity.domain.models.values import Password
from identity.infra.http.authentication import (
    get_identity_service,
    require_trusted_origin,
    session_cookie_name,
)
from identity.infra.http.routers.setup import setup_routers


@pytest.fixture
def service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def client(service: AsyncMock) -> TestClient:
    app = FastAPI()
    setup_routers(app)
    app.dependency_overrides[get_identity_service] = lambda: service
    app.dependency_overrides[require_trusted_origin] = lambda: None
    return TestClient(app)


@pytest.fixture
def real_service_client() -> Iterator[TestClient]:
    app = FastAPI()
    setup_routers(app)
    app.dependency_overrides[require_trusted_origin] = lambda: None
    with TestClient(app) as real_client:
        yield real_client


def session(account: Account) -> Session:
    return Session(
        account_id=account.id,
        token_hash="a" * 64,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )


def test_signup_returns_generic_message_and_session_cookie(client: TestClient, service: AsyncMock) -> None:
    account = Account(email="user@example.com", password_hash="hashed")  # noqa: S106
    service.signup.return_value = (account, session(account), "raw-session-token")

    response = client.post(
        "/identity/signup",
        json={"email": "USER@example.com", "password": "correct-horse"},
    )

    assert response.status_code == 202
    assert response.json() == {"message": "If the address can be registered, verification instructions will be sent"}
    assert response.cookies[session_cookie_name()] == "raw-session-token"
    service.signup.assert_awaited_once()


def test_signup_duplicate_email_has_same_response_without_cookie(client: TestClient, service: AsyncMock) -> None:
    service.signup.side_effect = DuplicateAccountEmail

    response = client.post(
        "/identity/signup",
        json={"email": "user@example.com", "password": "correct-horse"},
    )

    assert response.status_code == 202
    assert response.json()["message"] == "If the address can be registered, verification instructions will be sent"
    assert session_cookie_name() not in response.cookies


def test_signup_duplicate_email_matches_new_signup_message_with_real_service(
    real_service_client: TestClient,
) -> None:
    email = f"{uuid.uuid4()}@example.com"
    payload = {"email": email, "password": "correct-horse"}

    first_response = real_service_client.post("/identity/signup", json=payload)
    duplicate_response = real_service_client.post("/identity/signup", json=payload)

    assert first_response.status_code == duplicate_response.status_code == 202
    assert (
        first_response.json()
        == duplicate_response.json()
        == {"message": "If the address can be registered, verification instructions will be sent"}
    )


def test_login_returns_account_csrf_token_and_cookie(client: TestClient, service: AsyncMock) -> None:
    account = Account(
        email="user@example.com",
        password_hash="hashed",  # noqa: S106
        email_verified_at=datetime.now(UTC),
    )
    service.login.return_value = (account, session(account), "raw-session-token")

    response = client.post(
        "/identity/login",
        json={"email": "user@example.com", "password": "correct-horse"},
    )

    assert response.status_code == 200
    assert response.json()["account"] == {
        "id": str(account.id),
        "email": account.email,
        "email_verified": True,
    }
    assert response.json()["csrf_token"]
    assert response.cookies[session_cookie_name()] == "raw-session-token"


def test_login_hides_credential_failure_details(client: TestClient, service: AsyncMock) -> None:
    service.login.side_effect = AuthenticationError

    response = client.post(
        "/identity/login",
        json={"email": "user@example.com", "password": "correct-horse"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/identity/signup", {"email": "not-an-email", "password": "correct-horse"}),
        ("/identity/signup", {"email": "user@example.com", "password": "short"}),
        (
            "/identity/login",
            {"email": "user@example.com", "password": "x" * (Password.MAX_LEN + 1)},
        ),
    ],
)
def test_credentials_endpoints_reject_invalid_input(client: TestClient, path: str, payload: dict[str, str]) -> None:
    response = client.post(path, json=payload)

    assert response.status_code == 422


def test_verify_email_maps_expired_token_to_bad_request(client: TestClient, service: AsyncMock) -> None:
    service.verify_email.side_effect = InvalidCredentialToken

    response = client.post("/identity/verify-email", json={"token": "t" * 20})

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid or expired token"}


def test_password_reset_request_does_not_reveal_account_existence(client: TestClient, service: AsyncMock) -> None:
    response = client.post("/identity/password-reset", json={"email": "user@example.com"})

    assert response.status_code == 200
    assert response.json() == {"message": "If the account exists, a password reset email will be sent"}
    service.request_password_reset.assert_awaited_once()
