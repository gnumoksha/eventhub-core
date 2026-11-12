import json
import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest
from events.application.event.image import __get_service as __get_image_service
from events.application.event.service import EventService, __get_service
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
from shared.domain.error_handler import domain_error_handler
from shared.domain.errors import DomainError

from tests.conftest import (
    NOW,
    InMemoryEventImageService,
)

ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


@pytest.fixture
def mock_view_service() -> AsyncMock:
    return AsyncMock(spec=EventViewService)


@pytest.fixture
def client(
    service: EventService,
    image_service: InMemoryEventImageService,
    mock_view_service: AsyncMock,
) -> TestClient:
    app = FastAPI()
    app.add_exception_handler(DomainError, domain_error_handler)
    setup_routers(app)
    app.dependency_overrides[__get_service] = lambda: service
    app.dependency_overrides[__get_image_service] = lambda: image_service
    app.dependency_overrides[get_event_view_service] = lambda: mock_view_service
    app.dependency_overrides[require_common_session] = lambda: CommonAuthenticatedSession(
        account_id=uuid.uuid4(),
        organization_id=ORGANIZATION_ID,
    )
    app.dependency_overrides[require_csrf] = lambda: None
    return TestClient(app)


def event_payload() -> dict:
    start_at = NOW + timedelta(days=30)
    return {
        "title": "Festival",
        "description": "Music all day long",
        "age_rating": "AGE_14",
        "venue": {
            "type": "physical",
            "name": "Allianz Parque",
            "address": {
                "street": "Avenida Francisco Matarazzo",
                "number": "1705",
                "district": "Água Branca",
                "city": "São Paulo",
                "state": "SP",
                "postal_code": "05001-200",
            },
        },
        "period": {
            "start_at": start_at.isoformat(),
            "end_at": (start_at + timedelta(hours=6)).isoformat(),
        },
    }


def create_event(client: TestClient) -> dict:
    response = client.post(
        "/organizers/events",
        data={"event": json.dumps(event_payload())},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_get_event(client: TestClient):
    created = create_event(client)

    response = client.get(f"/organizers/events/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "DRAFT"
    assert body["venue"]["address"]["postal_code"] == "05001200"


def test_full_lifecycle(client: TestClient):
    event_id = create_event(client)["id"]
    new_start = NOW + timedelta(days=60)

    assert client.post(f"/organizers/events/{event_id}/publish").json()["status"] == "PUBLISHED"

    postponed = client.post(
        f"/organizers/events/{event_id}/postpone",
        json={
            "start_at": new_start.isoformat(),
            "end_at": (new_start + timedelta(hours=6)).isoformat(),
        },
    )
    assert postponed.json()["status"] == "POSTPONED"

    cancelled = client.post(f"/organizers/events/{event_id}/cancel", json={"reason": "Storm"})
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["cancellation_reason"] == "Storm"


def test_list_organization_events(client: TestClient):
    first = create_event(client)
    create_event(client)
    client.post(f"/organizers/events/{first['id']}/publish")

    response = client.get("/organizers/events", params={"status": "PUBLISHED"})

    assert response.status_code == 200
    assert [e["id"] for e in response.json()] == [first["id"]]


def test_change_venue_to_online(client: TestClient):
    event_id = create_event(client)["id"]
    payload = event_payload()
    payload["venue"] = {"type": "online", "url": "https://meet.example.com/x"}

    response = client.put(
        f"/organizers/events/{event_id}",
        json=payload,
    )

    assert response.status_code == 200
    assert response.json()["venue"] == {
        "type": "online",
        "url": "https://meet.example.com/x",
    }


def test_invalid_state_transition_returns_409(client: TestClient):
    event_id = create_event(client)["id"]
    client.post(f"/organizers/events/{event_id}/publish")

    response = client.post(f"/organizers/events/{event_id}/publish")

    assert response.status_code == 409


def test_invalid_domain_value_returns_422(client: TestClient):
    payload = event_payload()
    payload["venue"]["address"]["postal_code"] = "123"

    response = client.post("/organizers/events", json=payload)

    assert response.status_code == 422


def test_unknown_event_returns_404(client: TestClient):
    assert client.get(f"/organizers/events/{uuid.uuid4()}").status_code == 404


def test_create_event_with_banner(client: TestClient):
    response = client.post(
        "/organizers/events",
        data={"event": json.dumps(event_payload())},
        files={"banner": ("banner.png", b"\x89PNG\r\n\x1a\nimage", "image/png")},
    )

    assert response.status_code == 201, response.text
    assert response.json()["banner_url"].endswith("/1.png")
    assert response.json()["id"] in response.json()["banner_url"]


def test_replace_event_banner(client: TestClient):
    created = create_event(client)
    response = client.put(
        f"/organizers/events/{created['id']}/banner",
        files={"banner": ("banner.webp", b"RIFF0000WEBPdata", "image/webp")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["banner_url"].endswith("/1.webp")


def test_reject_banner_with_mismatched_signature(client: TestClient):
    response = client.post(
        "/organizers/events",
        data={"event": json.dumps(event_payload())},
        files={"banner": ("banner.png", b"not png", "image/png")},
    )

    assert response.status_code == 415


def test_record_view_returns_204(client: TestClient, mock_view_service: AsyncMock):
    event_id = uuid.uuid4()
    mock_view_service.record_view.return_value = True

    response = client.post(
        f"/organizers/events/{event_id}/views",
        headers={"User-Agent": "TestBrowser", "X-Session-ID": "sess-xyz"},
    )

    assert response.status_code == 204
    mock_view_service.record_view.assert_called_once()
    kwargs = mock_view_service.record_view.call_args[1]
    assert kwargs["event_id"] == event_id
    assert kwargs["user_agent"] == "TestBrowser"
    assert kwargs["session_token"] == "sess-xyz"


def test_record_view_with_invalid_uuid_returns_422(client: TestClient):
    response = client.post("/organizers/events/not-a-valid-uuid/views")
    assert response.status_code == 422


def test_get_views_authorized_returns_200(
    client: TestClient,
    mock_view_service: AsyncMock,
):
    created = create_event(client)
    event_id = created["id"]

    metrics = EventViewsMetrics(
        event_id=uuid.UUID(event_id),
        total_views=42,
        unique_visitors=30,
        daily_views=[DailyViews(date=date(2030, 1, 10), views=42, unique_visitors=30)],
    )
    mock_view_service.get_event_metrics.return_value = metrics

    response = client.get(f"/organizers/events/{event_id}/views")

    assert response.status_code == 200
    data = response.json()
    assert data["event_id"] == event_id
    assert data["total_views"] == 42
    assert data["unique_visitors"] == 30
    assert len(data["daily_views"]) == 1


def test_get_views_with_days_param(
    client: TestClient,
    mock_view_service: AsyncMock,
):
    created = create_event(client)
    event_id = uuid.UUID(created["id"])

    metrics = EventViewsMetrics(
        event_id=event_id,
        total_views=10,
        unique_visitors=8,
        daily_views=[],
    )
    mock_view_service.get_event_metrics.return_value = metrics

    response = client.get(f"/organizers/events/{event_id}/views?days=14")

    assert response.status_code == 200
    mock_view_service.get_event_metrics.assert_called_once_with(event_id, days=14)


def test_get_views_unauthorized_org_returns_403(
    client: TestClient,
):
    created = create_event(client)
    event_id = created["id"]

    client.app.dependency_overrides[require_common_session] = lambda: CommonAuthenticatedSession(
        account_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
    )

    response = client.get(f"/organizers/events/{event_id}/views")
    assert response.status_code == 403


def test_get_views_non_existent_event_returns_404(client: TestClient):
    event_id = uuid.uuid4()
    response = client.get(f"/organizers/events/{event_id}/views")
    assert response.status_code == 404
