import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

SCHEMA = "events"


class EventRecord(SQLModel, table=True):
    """Persistence model of the Event aggregate. Not exposed outside the infra layer."""

    __tablename__: str = "events"
    __table_args__ = {"schema": SCHEMA}

    id: uuid.UUID = Field(primary_key=True)
    organization_id: uuid.UUID = Field(index=True)
    title: str = Field(max_length=100)
    description: str
    age_rating: str = Field(max_length=2)
    status: str = Field(max_length=20, index=True)
    venue: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    start_at: datetime | None = None
    end_at: datetime | None = Field(default=None, index=True)
    cancellation_reason: str | None = Field(default=None, max_length=500)
    created_at: datetime
    updated_at: datetime
    version: int
