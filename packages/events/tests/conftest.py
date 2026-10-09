import uuid
from datetime import UTC, datetime, timedelta
from typing import override

import pytest
from events.application.event.service import EventService
from events.domain.models.event.event import Event
from events.domain.models.event.repository import EventRepository
from events.domain.models.event.values import (
    Address,
    AgeRating,
    EventID,
    EventPeriod,
    EventStatus,
    OrganizationID,
    PhysicalVenue,
)
from libs.events import PublishableEvent

NOW = datetime(2030, 1, 10, 12, 0, tzinfo=UTC)


class InMemoryEventRepository(EventRepository):
    def __init__(self) -> None:
        self.events: dict[EventID, Event] = {}
        self.outbox: list[PublishableEvent] = []

    @override
    def get(self, id: EventID) -> Event | None:
        return self.events.get(id)

    @override
    def save(self, event: Event) -> None:
        event.version += 1
        self.events[event.id] = event
        self.outbox.extend(event.pull_events())

    @override
    def list_by_organization(
        self,
        organization_id: OrganizationID,
        *,
        status: EventStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Event]:
        events = [
            e
            for e in self.events.values()
            if e.organization_id == organization_id and (status is None or e.status == status)
        ]
        return events[offset : offset + limit]

    @override
    def list_ended_but_not_finished(self, now: datetime, *, limit: int) -> list[Event]:
        return [
            e
            for e in self.events.values()
            if e.status in (EventStatus.PUBLISHED, EventStatus.POSTPONED) and e.period and e.period.has_ended(now)
        ][:limit]


class FakeClock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def make_period(days_from_now: int = 30, duration_hours: int = 4, now: datetime = NOW) -> EventPeriod:
    start_at = now + timedelta(days=days_from_now)
    return EventPeriod(start_at=start_at, end_at=start_at + timedelta(hours=duration_hours))


def make_venue() -> PhysicalVenue:
    return PhysicalVenue(
        name="Allianz Parque",
        address=Address(
            street="Avenida Francisco Matarazzo",
            number="1705",
            district="Água Branca",
            city="São Paulo",
            state="sp",
            postal_code="05001-200",
        ),
    )


def make_draft(*, with_venue: bool = True, with_period: bool = True) -> Event:
    return Event.create(
        organization_id=uuid.uuid4(),
        title="Rock in Rio",
        description="The biggest music festival",
        age_rating=AgeRating.AGE_14,
        venue=make_venue() if with_venue else None,
        period=make_period() if with_period else None,
        now=NOW,
    )


def make_published() -> Event:
    event = make_draft()
    event.publish(NOW)
    event.pull_events()
    return event


@pytest.fixture
def repository() -> InMemoryEventRepository:
    return InMemoryEventRepository()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def service(repository: InMemoryEventRepository, clock: FakeClock) -> EventService:
    return EventService(repository, clock)
