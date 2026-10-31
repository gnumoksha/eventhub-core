import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from identity.application.authentication import (
    IdentityService,
    csrf_token,
    verify_csrf_token,
)
from identity.domain.models.account.account import Account
from identity.domain.models.account.events import AccountWasDeactivated
from identity.domain.models.values import Password
from identity.infra.http.authentication import require_trusted_origin
from identity.infra.http.routers.setup import setup_routers

TEST_PASSWORD_HASH = "test-password-digest"


def test_csrf_token_is_bound_to_the_session_token() -> None:
    token = csrf_token("session-token", "application-secret")

    assert verify_csrf_token("session-token", "application-secret", token)
    assert not verify_csrf_token("another-session", "application-secret", token)
    assert not verify_csrf_token("session-token", "application-secret", None)


def test_account_deactivated_event_round_trips() -> None:
    event = AccountWasDeactivated(uuid.uuid4())

    restored = AccountWasDeactivated.from_dict(event.to_dict(), event.metadata)

    assert restored.to_dict() == event.to_dict()


@pytest.mark.asyncio
async def test_deactivate_account_revokes_access_and_publishes_event() -> None:
    account_id = uuid.uuid4()
    now = datetime(2030, 1, 1, tzinfo=UTC)
    account = Account(id=account_id, email="user@example.com", password_hash=TEST_PASSWORD_HASH)
    repository = AsyncMock()
    repository.get_account.return_value = account
    repository.get_active_sessions.return_value = []
    repository.get_unconsumed_credentials.return_value = []
    service = IdentityService(repository, AsyncMock())

    await service.deactivate_account(account_id, now=now)

    repository.save.assert_awaited_once()
    saved_events = repository.save.await_args.kwargs["events"]
    [event] = saved_events
    assert isinstance(event, AccountWasDeactivated)
    assert event.account_id == account_id
    assert account.deactivated_at == now


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
