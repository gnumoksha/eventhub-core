from collections.abc import Iterator
from datetime import timedelta

import pytest
from events.domain.errors import ConcurrencyConflict
from events.domain.models.event.values import EventStatus, OnlineVenue
from events.infra.persistence.sql_event_repository import SqlEventRepository
from shared.infra.database import engine
from shared.infra.outbox import OutboxMessage
from sqlmodel import Session, col, select

from tests.conftest import NOW, make_draft

pytestmark = pytest.mark.database_access


@pytest.fixture
def session() -> Iterator[Session]:
    """
    Everything happens inside a transaction that is rolled back at the end,
    so the test does not touch the data that already exists in the database.
    """
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
            yield session
        transaction.rollback()


@pytest.fixture
def repository(session: Session) -> SqlEventRepository:
    return SqlEventRepository(session)


def outbox_event_names(session: Session, event_id: object) -> list[str]:
    messages = session.exec(select(OutboxMessage).order_by(col(OutboxMessage.created_at))).all()
    return [m.event_name for m in messages if m.message["payload"].get("event_id") == str(event_id)]


def test_round_trip(repository: SqlEventRepository):
    event = make_draft()

    repository.save(event)
    loaded = repository.get(event.id)

    assert loaded is not None
    assert loaded.version == 1
    assert loaded.title == event.title
    assert loaded.venue == event.venue
    assert loaded.period == event.period
    assert loaded.status == EventStatus.DRAFT


def test_updates_and_increments_version(repository: SqlEventRepository):
    event = make_draft()
    repository.save(event)

    event.change_venue(OnlineVenue(url="https://meet.example.com/x"), NOW)
    event.publish(NOW)
    repository.save(event)

    loaded = repository.get(event.id)
    assert loaded is not None
    assert loaded.version == 2
    assert loaded.status == EventStatus.PUBLISHED
    assert loaded.venue == OnlineVenue(url="https://meet.example.com/x")


def test_concurrent_update_is_rejected(repository: SqlEventRepository):
    event = make_draft()
    repository.save(event)
    first = repository.get(event.id)
    second = repository.get(event.id)
    assert first is not None
    assert second is not None

    first.publish(NOW)
    repository.save(first)
    second.cancel("reason", NOW)

    with pytest.raises(ConcurrencyConflict):
        repository.save(second)


def test_list_ended_but_not_finished(repository: SqlEventRepository):
    event = make_draft()
    event.publish(NOW)
    repository.save(event)
    assert event.period is not None

    not_ended = repository.list_ended_but_not_finished(event.period.end_at - timedelta(seconds=1), limit=1000)
    assert event.id not in [e.id for e in not_ended]
    ended = repository.list_ended_but_not_finished(event.period.end_at, limit=1000)
    assert event.id in [e.id for e in ended]


def test_stores_integration_events_in_the_outbox(repository: SqlEventRepository, session: Session):
    event = make_draft()
    event.publish(NOW)

    repository.save(event)

    assert outbox_event_names(session, event.id) == ["eventhub:events:event.published"]
    assert event.pull_events() == []


def test_concurrency_conflict_does_not_store_integration_events(repository: SqlEventRepository, session: Session):
    event = make_draft()
    event.publish(NOW)
    repository.save(event)
    first = repository.get(event.id)
    second = repository.get(event.id)
    assert first is not None
    assert second is not None
    first.cancel("first", NOW)
    repository.save(first)

    second.cancel("second", NOW)
    with pytest.raises(ConcurrencyConflict):
        repository.save(second)

    assert outbox_event_names(session, event.id) == [
        "eventhub:events:event.published",
        "eventhub:events:event.cancelled",
    ]
