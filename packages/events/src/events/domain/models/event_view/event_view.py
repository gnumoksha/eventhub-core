import uuid
from datetime import UTC, datetime
from typing import Self

import uuid_utils.compat as uuid_compat
from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from events.domain.models.event.values import EventID


class EventView(SQLModel, table=True):
    __tablename__: str = "event_views"
    __table_args__ = (
        Index("ix_events_event_views_event_id_viewed_at", "event_id", "viewed_at"),
        Index("ix_events_event_views_event_id_visitor_hash", "event_id", "visitor_hash"),
        {"schema": "events"},
    )

    id: uuid.UUID = Field(default_factory=uuid_compat.uuid7, primary_key=True)
    event_id: EventID = Field(foreign_key="events.events.id", index=True)
    visitor_hash: str = Field(max_length=64)
    viewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def record(
        cls,
        *,
        event_id: EventID,
        visitor_hash: str,
        viewed_at: datetime | None = None,
    ) -> Self:
        return cls(
            event_id=event_id,
            visitor_hash=visitor_hash,
            viewed_at=viewed_at if viewed_at is not None else datetime.now(UTC),
        )
