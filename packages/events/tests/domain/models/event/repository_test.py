from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from events.domain.models.event.event import Event
from events.domain.models.event.repository import EventRepository
from events.domain.models.event.values import EventStatus, EventUpdate, OnlineVenue
from shared.domain.errors import ConcurrencyConflict
from shared.infra.database import engine
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
