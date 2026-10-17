from collections.abc import AsyncIterator
from typing import Self, override

import pytest
import pytest_asyncio
from libs.events import EventDispatchError, Metadata, PublishableEvent, RecordingDispatcher, SerializableDict
from shared.infra.database import engine
from shared.infra.domain_events import DomainEventsConfig
from shared.infra.outbox import OutboxMessage, OutboxRelay, add_to_outbox
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select, update

pytestmark = [pytest.mark.database_access, pytest.mark.asyncio]


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


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """
    Everything happens inside a transaction that is rolled back at the end,
    so the test does not touch the data that already exists in the database.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
            # hide the messages that were pending before the test
            await session.execute(
                update(OutboxMessage)
                .where(col(OutboxMessage.published_at).is_(None), col(OutboxMessage.discarded_at).is_(None))
                .values(discarded_at=func.now())
            )
            yield session
        await transaction.rollback()
    await engine.dispose()


async def stage(session: AsyncSession, *values: str) -> list[SomethingHappened]:
    events = [SomethingHappened(value) for value in values]
    add_to_outbox(session, events)
    await session.commit()
    return events


def values_of(dispatcher: RecordingDispatcher) -> list[str]:
    return [event.value for event in dispatcher.dispatched if isinstance(event, SomethingHappened)]


async def test_publishes_pending_messages_in_order(session: AsyncSession):
    events = await stage(session, "first", "second", "third")
    dispatcher = RecordingDispatcher()

    published = await OutboxRelay(session, dispatcher).relay()

    assert published == 3
    assert values_of(dispatcher) == ["first", "second", "third"]
    # the metadata is kept, so listeners can use the event id to detect duplicates
    assert [e.metadata.id for e in dispatcher.dispatched] == [e.metadata.id for e in events]
    assert await OutboxRelay(session, dispatcher).relay() == 0


async def test_marks_messages_as_published(session: AsyncSession):
    await stage(session, "first")

    await OutboxRelay(session, RecordingDispatcher()).relay()

    result = await session.execute(select(OutboxMessage).where(OutboxMessage.event_name == SomethingHappened.name()))
    message = result.scalars().one()
    assert message.published_at is not None
    assert message.attempts == 1


async def test_respects_batch_size(session: AsyncSession):
    await stage(session, "first", "second", "third")
    dispatcher = RecordingDispatcher()

    assert await OutboxRelay(session, dispatcher).relay(batch_size=2) == 2
    assert values_of(dispatcher) == ["first", "second"]


async def test_broker_failure_keeps_the_message_pending_and_stops(session: AsyncSession):
    await stage(session, "first", "second")

    assert await OutboxRelay(session, FailingDispatcher()).relay() == 0

    result = await session.execute(
        select(OutboxMessage)
        .where(OutboxMessage.event_name == SomethingHappened.name())
        .order_by(col(OutboxMessage.created_at))
    )
    first, second = result.scalars().all()
    assert first.attempts == 1
    assert first.last_error is not None
    assert first.published_at is None
    assert first.discarded_at is None
    assert second.attempts == 0  # it stopped to keep the order

    dispatcher = RecordingDispatcher()
    assert await OutboxRelay(session, dispatcher).relay() == 2
    assert values_of(dispatcher) == ["first", "second"]


async def test_discards_unknown_events_without_blocking_the_next_ones(session: AsyncSession):
    session.add(
        OutboxMessage(
            event_name="test:outbox.unknown",
            message={"name": "test:outbox.unknown", "metadata": Metadata().to_dict(), "payload": {}},
        )
    )
    await session.commit()
    await stage(session, "after the unknown one")
    dispatcher = RecordingDispatcher()

    assert await OutboxRelay(session, dispatcher).relay() == 1

    assert values_of(dispatcher) == ["after the unknown one"]
    result = await session.execute(select(OutboxMessage).where(OutboxMessage.event_name == "test:outbox.unknown"))
    unknown = result.scalars().one()
    assert unknown.discarded_at is not None
    assert unknown.last_error is not None
