# The Event entity

import uuid
from datetime import UTC, datetime

import uuid_utils.compat as uuid_compat
from sqlmodel import Field, SQLModel

EventID = uuid.UUID


class EventBase(SQLModel):
    id: EventID = Field(default_factory=uuid_compat.uuid7, primary_key=True)
    name: str = Field(max_length=100, default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = Field(
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
        sa_column_kwargs={"onupdate": lambda: datetime.now(UTC)},
    )


class Event(EventBase, table=True):
    __tablename__: str = "events"  # type:ignore
