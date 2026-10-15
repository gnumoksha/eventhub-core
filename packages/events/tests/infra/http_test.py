import uuid
from datetime import timedelta

import pytest
from events.application.event.service import EventService, __get_service
from events.infra.http.routers.setup import setup_routers
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import NOW


@pytest.fixture
def client(service: EventService) -> TestClient:
    app = FastAPI()
    setup_routers(app)
    app.dependency_overrides[__get_service] = lambda: service
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


def create_event(client: TestClient, organization_id: uuid.UUID | None = None) -> dict:
    response = client.post(f"/organizations/{organization_id or uuid.uuid4()}/events", json=event_payload())
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_get_event(client: TestClient):
    created = create_event(client)

    response = client.get(f"/events/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "DRAFT"
    assert body["venue"]["address"]["postal_code"] == "05001200"


def test_full_lifecycle(client: TestClient):
    event_id = create_event(client)["id"]
    new_start = NOW + timedelta(days=60)

    assert client.post(f"/events/{event_id}/publish").json()["status"] == "PUBLISHED"

    postponed = client.post(
        f"/events/{event_id}/postpone",
        json={"start_at": new_start.isoformat(), "end_at": (new_start + timedelta(hours=6)).isoformat()},
    )
    assert postponed.json()["status"] == "POSTPONED"

    cancelled = client.post(f"/events/{event_id}/cancel", json={"reason": "Storm"})
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["cancellation_reason"] == "Storm"


def test_list_organization_events(client: TestClient):
    organization_id = uuid.uuid4()
    first = create_event(client, organization_id)
    create_event(client, organization_id)
    client.post(f"/events/{first['id']}/publish")

    response = client.get(f"/organizations/{organization_id}/events", params={"status": "PUBLISHED"})

    assert response.status_code == 200
    assert [e["id"] for e in response.json()] == [first["id"]]


def test_change_venue_to_online(client: TestClient):
    event_id = create_event(client)["id"]

    response = client.put(f"/events/{event_id}/venue", json={"type": "online", "url": "https://meet.example.com/x"})

    assert response.status_code == 200
    assert response.json()["venue"] == {"type": "online", "url": "https://meet.example.com/x"}


def test_invalid_state_transition_returns_409(client: TestClient):
    event_id = create_event(client)["id"]
    client.post(f"/events/{event_id}/publish")

    response = client.post(f"/events/{event_id}/publish")

    assert response.status_code == 409


def test_invalid_domain_value_returns_422(client: TestClient):
    payload = event_payload()
    payload["venue"]["address"]["postal_code"] = "123"

    response = client.post(f"/organizations/{uuid.uuid4()}/events", json=payload)

    assert response.status_code == 422


def test_unknown_event_returns_404(client: TestClient):
    assert client.get(f"/events/{uuid.uuid4()}").status_code == 404
