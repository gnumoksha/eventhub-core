"""
Transactional outbox.

Integration events are stored in the same transaction as the aggregate that
recorded them, so a state change is never committed without its events (and
vice versa). The OutboxRelay publishes them to the broker afterwards.

The delivery is at-least-once: if the process crashes after publishing but
before marking the message as published, it is published again. Listeners must
be idempotent; they can use the event metadata id to detect duplicates.
"""

import json
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import uuid_utils.compat as uuid_compat
from libs.events import Dispatcher, EventDispatchError, JsonDecoder, JsonEncoder, PublishableEvent
from libs.events.encoding import UnmappedEventError
from shared.infra.logger import logger
from sqlalchemy import Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Field, SQLModel, col, select

_ERROR_MAX_LENGTH = 2000


class OutboxMessage(SQLModel, table=True):
    __tablename__: str = "outbox_messages"
    __table_args__ = (
        # only the pending messages are queried, so the index stays small as published messages pile up
        Index(
            "ix_outbox_messages_pending",
            "created_at",
            "id",
            postgresql_where=text("published_at IS NULL AND discarded_at IS NULL"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid_compat.uuid7, primary_key=True)
    event_name: str = Field(max_length=PublishableEvent.NAME_MAX_LENGTH)
    message: dict[str, Any] = Field(sa_type=JSONB)
    """The event encoded by JsonEncoder: name, metadata and payload."""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    published_at: datetime | None = None
    discarded_at: datetime | None = None
    """Set when the message can never be published (e.g. unknown event class). It needs manual intervention."""
    attempts: int = 0
    last_error: str | None = Field(default=None, max_length=_ERROR_MAX_LENGTH)

    @classmethod
    def from_event(cls, event: PublishableEvent) -> OutboxMessage:
        return cls(event_name=event.name(), message=json.loads(JsonEncoder().encode(event)))

    def to_event(self) -> PublishableEvent:
        """
        Raises:
            UnmappedEventError: if the event class was not loaded with load_events()
        """
        return JsonDecoder().decode(json.dumps(self.message))


def add_to_outbox(session: AsyncSession, events: Iterable[PublishableEvent]) -> None:
    """Stages the events in the session. They are persisted by the caller's commit."""
    session.add_all(OutboxMessage.from_event(event) for event in events)


class OutboxRelay:
    def __init__(self, session: AsyncSession, dispatcher: Dispatcher) -> None:
        self._session = session
        self._dispatcher = dispatcher

    async def relay(self, *, batch_size: int = 100) -> int:
        """
        Publishes up to batch_size pending messages, oldest first. Returns how many were published.

        Stops at the first dispatch failure (e.g. broker down) so that messages keep their order.
        """
        try:
            return await self._relay(batch_size)
        finally:
            # never leave a transaction open between calls: it would hold locks (blocking migrations) and block vacuum
            await self._session.rollback()

    async def _relay(self, batch_size: int) -> int:
        published = 0
        while published < batch_size:
            message = await self._claim_next()
            if message is None:
                break

            try:
                self._dispatcher.dispatch(message.to_event())
            except EventDispatchError as exc:
                await self._record_failure(message, exc)
                break
            except UnmappedEventError as exc:
                # it will never succeed until the code is fixed, so it must not block the next messages
                await self._record_failure(message, exc, give_up=True)
                continue

            message.published_at = datetime.now(UTC)
            message.attempts += 1
            await self._session.commit()
            published += 1

        return published

    async def _claim_next(self) -> OutboxMessage | None:
        """Locks the oldest pending message so that concurrent relays skip it."""
        query = (
            select(OutboxMessage)
            .where(col(OutboxMessage.published_at).is_(None), col(OutboxMessage.discarded_at).is_(None))
            .order_by(col(OutboxMessage.created_at), col(OutboxMessage.id))
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(query)
        return result.scalars().first()

    async def _record_failure(self, message: OutboxMessage, exc: Exception, *, give_up: bool = False) -> None:
        logger.exception("Could not publish outbox message %s (%s)", message.id, message.event_name)
        message.attempts += 1
        message.last_error = str(exc)[:_ERROR_MAX_LENGTH]
        if give_up:
            message.discarded_at = datetime.now(UTC)
        await self._session.commit()
