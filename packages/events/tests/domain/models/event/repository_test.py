from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from events.domain.models.event.event import Event
from events.domain.models.event.repository import EventRepository
from events.domain.models.event.values import EventPeriod, EventStatus, EventUpdate, OnlineVenue
from events.domain.models.event_view.event_view import EventView
from shared.domain.errors import ConcurrencyConflict
from shared.infra.database.sql import engine
from shared.infra.outbox import OutboxMessage
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from sqlmodel import col, select

from tests.conftest import NOW, make_draft

pytestmark = [pytest.mark.database_access, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def connection() -> AsyncIterator[AsyncConnection]:
    """
    Everything happens inside a transaction that is rolled back at the end,
    so the test does not touch the data that already exists in the database.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        yield connection
        await transaction.rollback()
    await engine.dispose()


def open_session(connection: AsyncConnection) -> AsyncSession:
    return AsyncSession(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)


@pytest_asyncio.fixture
async def session(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    async with open_session(connection) as session:
        yield session


@pytest.fixture
def repository(session: AsyncSession) -> EventRepository:
    return EventRepository(session)


@pytest_asyncio.fixture
async def concurrent_session(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """Simulates another request: its own session, so it loads its own copy of the event."""
    async with open_session(connection) as session:
        yield session


@pytest.fixture
def concurrent_repository(concurrent_session: AsyncSession) -> EventRepository:
    return EventRepository(concurrent_session)


async def load_concurrently(repository: EventRepository, session: AsyncSession, event: Event) -> Event:
    """
    Loads the event in the concurrent session and ends its read transaction.

    Both sessions share the test connection, where savepoints are a stack: if the read
    savepoint stayed open, rolling it back after the conflict would also undo the
    changes committed by the other session in the meantime.
    """
    loaded = await repository.get(event.id)
    assert loaded is not None
    await session.commit()
    return loaded


async def outbox_event_names(session: AsyncSession, event_id: object) -> list[str]:
    result = await session.execute(select(OutboxMessage).order_by(col(OutboxMessage.created_at)))
    messages = result.scalars().all()
    return [m.event_name for m in messages if m.message["payload"].get("event_id") == str(event_id)]


async def test_round_trip(repository: EventRepository, concurrent_repository: EventRepository):
    event = make_draft()

    await repository.save(event)
    loaded = await concurrent_repository.get(event.id)  # another session, so it really comes from the database

    assert loaded is not None
    assert loaded.version == 1
    assert loaded.title == event.title
    assert loaded.venue == event.venue
    assert loaded.period == event.period
    assert loaded.status == EventStatus.DRAFT


async def test_updates_and_increments_version(repository: EventRepository, concurrent_repository: EventRepository):
    event = make_draft()
    await repository.save(event)

    event.change_venue(OnlineVenue(url="https://meet.example.com/x"), NOW)
    event.publish(NOW)
    await repository.save(event)

    loaded = await concurrent_repository.get(event.id)
    assert loaded is not None
    assert loaded.version == 2
    assert loaded.status == EventStatus.PUBLISHED
    assert loaded.venue == OnlineVenue(url="https://meet.example.com/x")


async def test_concurrent_update_is_rejected(
    repository: EventRepository, concurrent_repository: EventRepository, concurrent_session: AsyncSession
):
    event = make_draft()
    await repository.save(event)
    second = await load_concurrently(concurrent_repository, concurrent_session, event)

    event.publish(NOW)
    await repository.save(event)
    second.cancel("reason", NOW)

    with pytest.raises(ConcurrencyConflict):
        await concurrent_repository.save(second)


async def test_list_ended_but_not_finished(repository: EventRepository):
    event = make_draft()
    event.publish(NOW)
    await repository.save(event)
    assert event.period is not None

    not_ended = await repository.list_ended_but_not_finished(event.period.end_at - timedelta(seconds=1), limit=1000)
    assert event.id not in [e.id for e in not_ended]
    ended = await repository.list_ended_but_not_finished(event.period.end_at, limit=1000)
    assert event.id in [e.id for e in ended]


async def test_stores_integration_events_in_the_outbox(repository: EventRepository, session: AsyncSession):
    event = make_draft()
    event.publish(NOW)

    await repository.save(event)

    assert await outbox_event_names(session, event.id) == ["eventhub.events.event.published"]
    assert event.pull_events() == []


async def test_stores_event_updated_in_the_outbox(repository: EventRepository, session: AsyncSession):
    event = make_draft()
    await repository.save(event)

    event.update(
        EventUpdate(
            title="Updated title",
            description=event.description,
            age_rating=event.age_rating,
            venue=event.venue,
            period=event.period,
        ),
        now=NOW,
    )
    await repository.save(event)

    assert await outbox_event_names(session, event.id) == ["eventhub.events.event.updated"]
    assert event.pull_events() == []


async def test_concurrency_conflict_does_not_store_integration_events(
    repository: EventRepository,
    concurrent_repository: EventRepository,
    concurrent_session: AsyncSession,
    session: AsyncSession,
):
    event = make_draft()
    event.publish(NOW)
    await repository.save(event)
    second = await load_concurrently(concurrent_repository, concurrent_session, event)
    event.cancel("first", NOW)
    await repository.save(event)

    second.cancel("second", NOW)
    with pytest.raises(ConcurrencyConflict):
        await concurrent_repository.save(second)

    assert await outbox_event_names(session, event.id) == [
        "eventhub.events.event.published",
        "eventhub.events.event.cancelled",
    ]


async def test_find_available_slug(repository: EventRepository):
    # When no slug exists
    slug1 = await repository.find_available_slug("festival")
    assert slug1 == "festival"

    ev1 = make_draft()
    ev1.slug = "festival"
    await repository.save(ev1)

    # When "festival" exists
    slug2 = await repository.find_available_slug("festival")
    assert slug2 == "festival-2"

    ev2 = make_draft()
    ev2.slug = "festival-2"
    await repository.save(ev2)

    # When "festival" and "festival-2" exist
    slug3 = await repository.find_available_slug("festival")
    assert slug3 == "festival-3"

    # Excluding own event id
    own_slug = await repository.find_available_slug("festival", exclude_event_id=ev1.id)
    assert own_slug == "festival"


async def test_list_public(repository: EventRepository, session: AsyncSession):
    # Event 1: published, starts in 20 days, has 2 views
    ev1 = make_draft()
    ev1.title = "Festival Pop"
    ev1.slug = "festival-pop"
    ev1.publish(NOW)
    await repository.save(ev1)

    v1 = EventView.record(event_id=ev1.id, visitor_hash="hash1")
    v2 = EventView.record(event_id=ev1.id, visitor_hash="hash2")
    session.add_all([v1, v2])

    # Event 2: published, starts in 5 days, has 0 views
    ev2 = make_draft()
    ev2.title = "Jazz Night"
    ev2.slug = "jazz-night"
    ev2.schedule(EventPeriod(start_at=NOW + timedelta(days=5), end_at=NOW + timedelta(days=5, hours=3)), NOW)
    ev2.publish(NOW)
    await repository.save(ev2)

    # Event 3: published, starts in 15 days, has 0 views
    ev3 = make_draft()
    ev3.title = "Indie Fest"
    ev3.slug = "indie-fest"
    ev3.schedule(EventPeriod(start_at=NOW + timedelta(days=15), end_at=NOW + timedelta(days=15, hours=3)), NOW)
    ev3.publish(NOW)
    await repository.save(ev3)

    # Event 4: draft (should be excluded)
    ev4 = make_draft()
    ev4.slug = "draft-event"
    await repository.save(ev4)

    await session.commit()

    events, total = await repository.list_public(NOW, limit=10, offset=0)
    assert total == 3
    assert len(events) == 3
    # ev1 has 2 views -> 1st
    # ev2 has 0 views and starts in 5 days -> 2nd
    # ev3 has 0 views and starts in 15 days -> 3rd
    assert [e.id for e in events] == [ev1.id, ev2.id, ev3.id]
