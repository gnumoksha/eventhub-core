import uuid
from datetime import timedelta

import pytest
from events.application.event.image import __get_service as __get_image_service
from events.application.event.service import EventService, __get_service
from events.domain.models.event.values import (
    Address,
    AgeRating,
    EventPeriod,
    EventStatus,
    PhysicalVenue,
)
from events.infra.http.routers.setup import setup_routers
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shared.domain.error_handler import domain_error_handler
from shared.domain.errors import DomainError

from tests.conftest import NOW, InMemoryEventImageService, InMemoryEventRepository


@pytest.fixture
def client(
    service: EventService,
    image_service: InMemoryEventImageService,
) -> TestClient:
    app = FastAPI()
    app.add_exception_handler(DomainError, domain_error_handler)
    setup_routers(app)
    app.dependency_overrides[__get_service] = lambda: service
    app.dependency_overrides[__get_image_service] = lambda: image_service
    return TestClient(app)


def _venue():
    return PhysicalVenue(
        name="Allianz Parque",
        address=Address(
            street="Avenida Francisco Matarazzo",
            number="1705",
            district="Água Branca",
            city="São Paulo",
            state="SP",
            postal_code="05001-200",
        ),
    )


@pytest.mark.asyncio
async def test_list_public_events_returns_only_active_published_and_postponed(
    client: TestClient, service: EventService
):
    org_id = uuid.uuid4()

    # Draft event (should be excluded)
    await service.create(
        organization_id=org_id,
        title="Draft Event",
        description="Draft",
        age_rating=AgeRating.ALL_AGES,
        venue=_venue(),
        period=EventPeriod(start_at=NOW + timedelta(days=10), end_at=NOW + timedelta(days=10, hours=2)),
    )

    # Published future event (should be included)
    pub_future = await service.create(
        organization_id=org_id,
        title="Published Future",
        description="Pub",
        age_rating=AgeRating.ALL_AGES,
        venue=_venue(),
        period=EventPeriod(start_at=NOW + timedelta(days=5), end_at=NOW + timedelta(days=5, hours=3)),
    )
    await service.publish(pub_future.id)

    # Postponed future event (should be included)
    postponed_event = await service.create(
        organization_id=org_id,
        title="Postponed Future",
        description="Postponed",
        age_rating=AgeRating.AGE_16,
        venue=_venue(),
        period=EventPeriod(start_at=NOW + timedelta(days=2), end_at=NOW + timedelta(days=2, hours=3)),
    )
    await service.publish(postponed_event.id)
    await service.postpone(
        postponed_event.id,
        EventPeriod(start_at=NOW + timedelta(days=20), end_at=NOW + timedelta(days=20, hours=3)),
    )

    # Finished / past event (should be excluded)
    past_event = await service.create(
        organization_id=org_id,
        title="Past Event",
        description="Past",
        age_rating=AgeRating.ALL_AGES,
        venue=_venue(),
        period=EventPeriod(start_at=NOW - timedelta(days=10), end_at=NOW - timedelta(days=9)),
    )
    past_event.status = EventStatus.FINISHED

    # Cancelled event (should be excluded)
    cancelled = await service.create(
        organization_id=org_id,
        title="Cancelled Event",
        description="Cancelled",
        age_rating=AgeRating.ALL_AGES,
        venue=_venue(),
        period=EventPeriod(start_at=NOW + timedelta(days=15), end_at=NOW + timedelta(days=15, hours=2)),
    )
    await service.publish(cancelled.id)
    await service.cancel(cancelled.id, "Emergency")

    # Call public endpoint without auth
    response = client.get("/events")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 2
    assert data["limit"] == 10
    assert data["offset"] == 0

    slugs = [item["slug"] for item in data["items"]]
    assert slugs == ["published-future", "postponed-future"]


@pytest.mark.asyncio
async def test_list_public_events_response_fields(client: TestClient, service: EventService):
    org_id = uuid.uuid4()
    event = await service.create(
        organization_id=org_id,
        title="Specific Fields Festival",
        description="Description that should NOT be in public list output",
        age_rating=AgeRating.AGE_14,
        venue=_venue(),
        period=EventPeriod(start_at=NOW + timedelta(days=3), end_at=NOW + timedelta(days=3, hours=5)),
    )
    await service.publish(event.id)

    response = client.get("/events")
    assert response.status_code == 200

    items = response.json()["items"]
    assert len(items) == 1
    item = items[0]

    # Exactly required fields
    assert set(item.keys()) == {"title", "slug", "venue", "period", "banner_url", "age_rating"}
    assert item["title"] == "Specific Fields Festival"
    assert item["slug"] == "specific-fields-festival"
    assert item["age_rating"] == "AGE_14"
    assert item["venue"]["type"] == "physical"
    assert item["period"]["start_at"] is not None
    assert item["banner_url"] is None
    # Ensure ID is not exposed
    assert "id" not in item


@pytest.mark.asyncio
async def test_list_public_events_ordering_views_then_date(
    client: TestClient, service: EventService, repository: InMemoryEventRepository
):
    org_id = uuid.uuid4()

    # Event 1: starts in 30 days, 5 views
    ev1 = await service.create(
        organization_id=org_id,
        title="Event Views 5 Starts in 30 Days",
        description="desc",
        age_rating=AgeRating.ALL_AGES,
        venue=_venue(),
        period=EventPeriod(start_at=NOW + timedelta(days=30), end_at=NOW + timedelta(days=30, hours=2)),
    )
    await service.publish(ev1.id)

    # Event 2: starts in 10 days, 20 views (should be first)
    ev2 = await service.create(
        organization_id=org_id,
        title="Event Views 20 Starts in 10 Days",
        description="desc",
        age_rating=AgeRating.ALL_AGES,
        venue=_venue(),
        period=EventPeriod(start_at=NOW + timedelta(days=10), end_at=NOW + timedelta(days=10, hours=2)),
    )
    await service.publish(ev2.id)

    # Event 3: starts in 3 days, 0 views (should be 3rd because date is closer)
    ev3 = await service.create(
        organization_id=org_id,
        title="Event Views 0 Starts in 3 Days",
        description="desc",
        age_rating=AgeRating.ALL_AGES,
        venue=_venue(),
        period=EventPeriod(start_at=NOW + timedelta(days=3), end_at=NOW + timedelta(days=3, hours=2)),
    )
    await service.publish(ev3.id)

    # Event 4: starts in 15 days, 0 views (should be 4th because date is further)
    ev4 = await service.create(
        organization_id=org_id,
        title="Event Views 0 Starts in 15 Days",
        description="desc",
        age_rating=AgeRating.ALL_AGES,
        venue=_venue(),
        period=EventPeriod(start_at=NOW + timedelta(days=15), end_at=NOW + timedelta(days=15, hours=2)),
    )
    await service.publish(ev4.id)

    repository.views_count = {
        ev1.id: 5,
        ev2.id: 20,
    }

    response = client.get("/events")
    assert response.status_code == 200
    items = response.json()["items"]
    slugs = [item["slug"] for item in items]
    assert slugs == [
        "event-views-20-starts-in-10-days",
        "event-views-5-starts-in-30-days",
        "event-views-0-starts-in-3-days",
        "event-views-0-starts-in-15-days",
    ]


@pytest.mark.asyncio
async def test_list_public_events_pagination(client: TestClient, service: EventService):
    org_id = uuid.uuid4()
    for i in range(15):
        ev = await service.create(
            organization_id=org_id,
            title=f"Paginated Event {i:02d}",
            description="desc",
            age_rating=AgeRating.ALL_AGES,
            venue=_venue(),
            period=EventPeriod(start_at=NOW + timedelta(days=i + 1), end_at=NOW + timedelta(days=i + 1, hours=2)),
        )
        await service.publish(ev.id)

    # Page 1 (limit 10)
    page1 = client.get("/events?limit=10&offset=0").json()
    assert page1["total"] == 15
    assert page1["limit"] == 10
    assert page1["offset"] == 0
    assert len(page1["items"]) == 10

    # Page 2 (offset 10)
    page2 = client.get("/events?limit=10&offset=10").json()
    assert page2["total"] == 15
    assert page2["limit"] == 10
    assert page2["offset"] == 10
    assert len(page2["items"]) == 5

    # Check distinct items
    slugs1 = {item["slug"] for item in page1["items"]}
    slugs2 = {item["slug"] for item in page2["items"]}
    assert len(slugs1.intersection(slugs2)) == 0
