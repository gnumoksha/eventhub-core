from collections.abc import Iterator
from typing import Self, override

import pytest
from libs.events import EventDispatchError, Metadata, PublishableEvent, RecordingDispatcher, SerializableDict
from shared.infra.database import engine
from shared.infra.domain_events import DomainEventsConfig
from shared.infra.outbox import OutboxMessage, OutboxRelay, add_to_outbox
from sqlalchemy import func
from sqlmodel import Session, col, select, update

pytestmark = pytest.mark.database_access


class SomethingHappened(PublishableEvent, name="test:outbox.something_happened"):
    def __init__(self, value: str, metadata: Metadata | None = None) -> None:
        super().__init__(DomainEventsConfig(), metadata)
        self.value = value

    @override
    def to_dict(self) -> SerializableDict:
        return {"value": self.value}

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(str(payload["value"]), metadata)


class FailingDispatcher(RecordingDispatcher):
    @override
    def dispatch(self, event: PublishableEvent) -> None:
        raise EventDispatchError(f"broker is down, could not publish {event.name()}")


@pytest.fixture
def session() -> Iterator[Session]:
    """
    Everything happens inside a transaction that is rolled back at the end,
    so the test does not touch the data that already exists in the database.
    """
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
            # hide the messages that were pending before the test
            session.exec(
                update(OutboxMessage)
                .where(col(OutboxMessage.published_at).is_(None), col(OutboxMessage.discarded_at).is_(None))
                .values(discarded_at=func.now())
            )
            yield session
        transaction.rollback()


def stage(session: Session, *values: str) -> list[SomethingHappened]:
    events = [SomethingHappened(value) for value in values]
    add_to_outbox(session, events)
    session.commit()
    return events


def values_of(dispatcher: RecordingDispatcher) -> list[str]:
    return [event.value for event in dispatcher.dispatched if isinstance(event, SomethingHappened)]


def test_publishes_pending_messages_in_order(session: Session):
    events = stage(session, "first", "second", "third")
    dispatcher = RecordingDispatcher()

    published = OutboxRelay(session, dispatcher).relay()

    assert published == 3
    assert values_of(dispatcher) == ["first", "second", "third"]
    # the metadata is kept, so listeners can use the event id to detect duplicates
    assert [e.metadata.id for e in dispatcher.dispatched] == [e.metadata.id for e in events]
    assert OutboxRelay(session, dispatcher).relay() == 0


def test_marks_messages_as_published(session: Session):
    stage(session, "first")

    OutboxRelay(session, RecordingDispatcher()).relay()

    message = session.exec(select(OutboxMessage).where(OutboxMessage.event_name == SomethingHappened.name())).one()
    assert message.published_at is not None
    assert message.attempts == 1


def test_respects_batch_size(session: Session):
    stage(session, "first", "second", "third")
    dispatcher = RecordingDispatcher()

    assert OutboxRelay(session, dispatcher).relay(batch_size=2) == 2
    assert values_of(dispatcher) == ["first", "second"]


def test_broker_failure_keeps_the_message_pending_and_stops(session: Session):
    stage(session, "first", "second")

    assert OutboxRelay(session, FailingDispatcher()).relay() == 0

    first, second = session.exec(
        select(OutboxMessage)
        .where(OutboxMessage.event_name == SomethingHappened.name())
        .order_by(col(OutboxMessage.created_at))
    ).all()
    assert first.attempts == 1
    assert first.last_error is not None
    assert first.published_at is None
    assert first.discarded_at is None
    assert second.attempts == 0  # it stopped to keep the order

    dispatcher = RecordingDispatcher()
    assert OutboxRelay(session, dispatcher).relay() == 2
    assert values_of(dispatcher) == ["first", "second"]


def test_discards_unknown_events_without_blocking_the_next_ones(session: Session):
    session.add(
        OutboxMessage(
            event_name="test:outbox.unknown",
            message={"name": "test:outbox.unknown", "metadata": Metadata().to_dict(), "payload": {}},
        )
    )
    session.commit()
    stage(session, "after the unknown one")
    dispatcher = RecordingDispatcher()

    assert OutboxRelay(session, dispatcher).relay() == 1

    assert values_of(dispatcher) == ["after the unknown one"]
    unknown = session.exec(select(OutboxMessage).where(OutboxMessage.event_name == "test:outbox.unknown")).one()
    assert unknown.discarded_at is not None
    assert unknown.last_error is not None
