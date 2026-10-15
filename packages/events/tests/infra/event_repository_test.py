from collections.abc import Iterator
from datetime import timedelta

import pytest
from events.domain.models.event.event import Event
from events.domain.models.event.repository import EventRepository
from events.domain.models.event.values import EventStatus, OnlineVenue
from shared.domain.errors import ConcurrencyConflict
from shared.infra.database import engine
from shared.infra.outbox import OutboxMessage
from sqlalchemy import Connection
from sqlmodel import Session, col, select

from tests.conftest import NOW, make_draft

pytestmark = pytest.mark.database_access


@pytest.fixture
def connection() -> Iterator[Connection]:
    """
    Everything happens inside a transaction that is rolled back at the end,
    so the test does not touch the data that already exists in the database.
    """
    with engine.connect() as connection:
        transaction = connection.begin()
        yield connection
        transaction.rollback()


def open_session(connection: Connection) -> Session:
    return Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)


@pytest.fixture
def session(connection: Connection) -> Iterator[Session]:
    with open_session(connection) as session:
        yield session


@pytest.fixture
def repository(session: Session) -> EventRepository:
    return EventRepository(session)


@pytest.fixture
def concurrent_session(connection: Connection) -> Iterator[Session]:
    """Simulates another request: its own session, so it loads its own copy of the event."""
    with open_session(connection) as session:
        yield session


@pytest.fixture
def concurrent_repository(concurrent_session: Session) -> EventRepository:
    return EventRepository(concurrent_session)


def load_concurrently(repository: EventRepository, session: Session, event: Event) -> Event:
    """
    Loads the event in the concurrent session and ends its read transaction.

    Both sessions share the test connection, where savepoints are a stack: if the read
    savepoint stayed open, rolling it back after the conflict would also undo the
    changes committed by the other session in the meantime.
    """
    loaded = repository.get(event.id)
    assert loaded is not None
    session.commit()
    return loaded


def outbox_event_names(session: Session, event_id: object) -> list[str]:
    messages = session.exec(select(OutboxMessage).order_by(col(OutboxMessage.created_at))).all()
    return [m.event_name for m in messages if m.message["payload"].get("event_id") == str(event_id)]


def test_round_trip(repository: EventRepository, concurrent_repository: EventRepository):
    event = make_draft()

    repository.save(event)
    loaded = concurrent_repository.get(event.id)  # another session, so it really comes from the database

    assert loaded is not None
    assert loaded.version == 1
    assert loaded.title == event.title
    assert loaded.venue == event.venue
    assert loaded.period == event.period
    assert loaded.status == EventStatus.DRAFT


def test_updates_and_increments_version(repository: EventRepository, concurrent_repository: EventRepository):
    event = make_draft()
    repository.save(event)

    event.change_venue(OnlineVenue(url="https://meet.example.com/x"), NOW)
    event.publish(NOW)
    repository.save(event)

    loaded = concurrent_repository.get(event.id)
    assert loaded is not None
    assert loaded.version == 2
    assert loaded.status == EventStatus.PUBLISHED
    assert loaded.venue == OnlineVenue(url="https://meet.example.com/x")


def test_concurrent_update_is_rejected(
    repository: EventRepository, concurrent_repository: EventRepository, concurrent_session: Session
):
    event = make_draft()
    repository.save(event)
    second = load_concurrently(concurrent_repository, concurrent_session, event)

    event.publish(NOW)
    repository.save(event)
    second.cancel("reason", NOW)

    with pytest.raises(ConcurrencyConflict):
        concurrent_repository.save(second)


def test_list_ended_but_not_finished(repository: EventRepository):
    event = make_draft()
    event.publish(NOW)
    repository.save(event)
    assert event.period is not None

    not_ended = repository.list_ended_but_not_finished(event.period.end_at - timedelta(seconds=1), limit=1000)
    assert event.id not in [e.id for e in not_ended]
    ended = repository.list_ended_but_not_finished(event.period.end_at, limit=1000)
    assert event.id in [e.id for e in ended]


def test_stores_integration_events_in_the_outbox(repository: EventRepository, session: Session):
    event = make_draft()
    event.publish(NOW)

    repository.save(event)

    assert outbox_event_names(session, event.id) == ["eventhub:events:event.published"]
    assert event.pull_events() == []


def test_concurrency_conflict_does_not_store_integration_events(
    repository: EventRepository, concurrent_repository: EventRepository, concurrent_session: Session, session: Session
):
    event = make_draft()
    event.publish(NOW)
    repository.save(event)
    second = load_concurrently(concurrent_repository, concurrent_session, event)
    event.cancel("first", NOW)
    repository.save(event)

    second.cancel("second", NOW)
    with pytest.raises(ConcurrencyConflict):
        concurrent_repository.save(second)

    assert outbox_event_names(session, event.id) == [
        "eventhub:events:event.published",
        "eventhub:events:event.cancelled",
    ]
