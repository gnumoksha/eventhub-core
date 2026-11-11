import uuid
from datetime import date
from unittest.mock import AsyncMock

import pytest
from events.application.event.service import (
    EventNotFound,
    EventService,
)
from events.application.event.service import (
    __get_service as __get_event_service,
)
from events.application.event_view.service import (
    EventViewService,
    get_event_view_service,
)
from events.domain.models.event_view.values import (
    DailyViews,
    EventViewsMetrics,
)
from events.infra.http.routers.setup import setup_routers
from fastapi import FastAPI
from fastapi.testclient import TestClient
from identity.infra.http.authentication import (
    CommonAuthenticatedSession,
    require_common_session,
    require_csrf,
)

from tests.conftest import make_draft

ORG_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
ORG_B = uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def mock_view_service() -> AsyncMock:
    return AsyncMock(spec=EventViewService)


@pytest.fixture
def mock_event_service() -> AsyncMock:
    return AsyncMock(spec=EventService)


@pytest.fixture
def client(
    mock_event_service: AsyncMock,
    mock_view_service: AsyncMock,
) -> TestClient:
    app = FastAPI()
    setup_routers(app)

    app.dependency_overrides[__get_event_service] = lambda: mock_event_service
    app.dependency_overrides[get_event_view_service] = lambda: mock_view_service
    app.dependency_overrides[require_common_session] = lambda: CommonAuthenticatedSession(
        account_id=uuid.uuid4(),
        organization_id=ORG_A,
    )
    app.dependency_overrides[require_csrf] = lambda: None

    return TestClient(app)


def test_record_view_returns_204(client: TestClient, mock_view_service: AsyncMock):
    event_id = uuid.uuid4()
    mock_view_service.record_view.return_value = True

    response = client.post(
        f"/events/{event_id}/views",
        headers={"User-Agent": "TestBrowser", "X-Session-ID": "sess-xyz"},
    )

    assert response.status_code == 204
    mock_view_service.record_view.assert_called_once()
    kwargs = mock_view_service.record_view.call_args[1]
    assert kwargs["event_id"] == event_id
    assert kwargs["user_agent"] == "TestBrowser"
    assert kwargs["session_token"] == "sess-xyz"


def test_record_view_with_invalid_uuid_returns_422(client: TestClient):
    response = client.post("/events/not-a-valid-uuid/views")
    assert response.status_code == 422


def test_get_views_authorized_returns_200(
    client: TestClient,
    mock_event_service: AsyncMock,
    mock_view_service: AsyncMock,
):
    event = make_draft()
    event.organization_id = ORG_A
    mock_event_service.get.return_value = event

    metrics = EventViewsMetrics(
        event_id=event.id,
        total_views=42,
        unique_visitors=30,
        daily_views=[DailyViews(date=date(2030, 1, 10), views=42, unique_visitors=30)],
    )
    mock_view_service.get_event_metrics.return_value = metrics

    response = client.get(f"/events/{event.id}/views")

    assert response.status_code == 200
    data = response.json()
    assert data["event_id"] == str(event.id)
    assert data["total_views"] == 42
    assert data["unique_visitors"] == 30
    assert len(data["daily_views"]) == 1


def test_get_views_with_days_param(
    client: TestClient,
    mock_event_service: AsyncMock,
    mock_view_service: AsyncMock,
):
    event = make_draft()
    event.organization_id = ORG_A
    mock_event_service.get.return_value = event

    metrics = EventViewsMetrics(
        event_id=event.id,
        total_views=10,
        unique_visitors=8,
        daily_views=[],
    )
    mock_view_service.get_event_metrics.return_value = metrics

    response = client.get(f"/events/{event.id}/views?days=14")

    assert response.status_code == 200
    mock_view_service.get_event_metrics.assert_called_once_with(event.id, days=14)


def test_get_views_unauthorized_org_returns_403(
    client: TestClient,
    mock_event_service: AsyncMock,
):
    event = make_draft()
    event.organization_id = ORG_B  # Caller belongs to ORG_A
    mock_event_service.get.return_value = event

    response = client.get(f"/events/{event.id}/views")
    assert response.status_code == 403


def test_get_views_non_existent_event_returns_404(
    client: TestClient,
    mock_event_service: AsyncMock,
):
    event_id = uuid.uuid4()
    mock_event_service.get.side_effect = EventNotFound(event_id)

    response = client.get(f"/events/{event_id}/views")
    assert response.status_code == 404
