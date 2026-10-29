# The Event aggregate root

from datetime import datetime
from typing import Any, Self

import uuid_utils.compat as uuid_compat
from libs.events import PublishableEvent
from pydantic import PrivateAttr
from shared.domain.errors import InvalidStateTransition, InvalidValue
from sqlalchemy import Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declared_attr, reconstructor
from sqlmodel import Field, SQLModel

from events.domain.models.event.events import (
    EventCancelled,
    EventFinished,
    EventPostponed,
    EventPublished,
    EventUpdated,
)
from events.domain.models.event.values import (
    Address,
    AgeRating,
    EventID,
    EventPeriod,
    EventStatus,
    EventUpdate,
    OnlineVenue,
    OrganizationID,
    PhysicalVenue,
    Venue,
)

TITLE_MAX_LENGTH = 100
DESCRIPTION_MAX_LENGTH = 10_000
CANCELLATION_REASON_MAX_LENGTH = 500
BANNER_IMAGE_KEY_MAX_LENGTH = 512

_EDITABLE_STATUSES = (EventStatus.DRAFT, EventStatus.PUBLISHED, EventStatus.POSTPONED)
_ON_SALE_STATUSES = (EventStatus.PUBLISHED, EventStatus.POSTPONED)


class Event(SQLModel, table=True):
    """
    The event as a product: what happens, where and when.

    Ticket types, batches and prices do not live here; they belong to Sales.

    Lifecycle: Draft -> Published -> (Postponed) -> Cancelled | Finished

    Change the event only through its methods, which enforce the domain rules;
    do not assign the fields directly.
    """

    __tablename__: str = "events"
    __table_args__ = {"schema": "events"}

    id: EventID = Field(default_factory=uuid_compat.uuid7, primary_key=True)
    organization_id: OrganizationID = Field(index=True)
    title: str = Field(max_length=TITLE_MAX_LENGTH)
    description: str
    # inherit_schema: the PostgreSQL enum type is created in the schema of the table
    age_rating: AgeRating = Field(sa_type=Enum(AgeRating, inherit_schema=True))
    status: EventStatus = Field(default=EventStatus.DRAFT, sa_type=Enum(EventStatus, inherit_schema=True), index=True)
    venue_data: dict[str, Any] | None = Field(default=None, sa_type=JSONB, sa_column_kwargs={"name": "venue"})
    """Use the venue property instead."""
    start_at: datetime | None = None
    end_at: datetime | None = Field(default=None, index=True)
    cancellation_reason: str | None = Field(default=None, max_length=CANCELLATION_REASON_MAX_LENGTH)
    banner_image_key: str | None = Field(default=None, max_length=BANNER_IMAGE_KEY_MAX_LENGTH)
    created_at: datetime
    updated_at: datetime
    version: int = 0
    """Incremented on every update. Used for optimistic locking."""

    _pending_events: list[PublishableEvent] = PrivateAttr(default_factory=list)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:  # noqa: N805
        # optimistic locking: an UPDATE fails with StaleDataError if someone else changed the row since it was loaded
        return {"version_id_col": cls.__table__.c.version}  # ty:ignore[unresolved-attribute]

    @reconstructor
    def _init_on_load(self) -> None:
        # SQLAlchemy does not call __init__ when loading from the database, so the private attributes are not set
        self.__pydantic_private__ = {"_pending_events": []}

    @classmethod
    def create(  # noqa: PLR0913
        cls,
        *,
        organization_id: OrganizationID,
        title: str,
        description: str,
        age_rating: AgeRating,
        now: datetime,
        venue: Venue | None = None,
        period: EventPeriod | None = None,
    ) -> Self:
        """Creates a new event as a draft."""
        # table models skip the Pydantic validation, so the domain rules are checked explicitly
        event = cls(
            organization_id=organization_id,
            title=_validate_title(title),
            description=_validate_description(description),
            age_rating=age_rating,
            status=EventStatus.DRAFT,
            created_at=now,
            updated_at=now,
        )
        event._set_venue(venue)
        event._set_period(period)
        return event

    @property
    def venue(self) -> Venue | None:
        return _venue_from_dict(self.venue_data)

    @property
    def period(self) -> EventPeriod | None:
        if self.start_at is None or self.end_at is None:
            return None
        return EventPeriod(start_at=self.start_at, end_at=self.end_at)

    def update(self, event_update: EventUpdate, *, now: datetime) -> None:
        """Replaces the editable event details while preserving lifecycle rules."""
        if self.status not in _EDITABLE_STATUSES:
            raise InvalidStateTransition(f"A {self.status} event cannot be edited")

        title = _validate_title(event_update.title)
        description = _validate_description(event_update.description)
        venue_changed = event_update.venue != self.venue
        period_changed = event_update.period != self.period

        if self.status != EventStatus.DRAFT and venue_changed:
            raise InvalidStateTransition("The venue can only be changed while the event is a draft")
        if self.status != EventStatus.DRAFT and period_changed:
            raise InvalidStateTransition("A published event can only be rescheduled by postponing it")

        self.title = title
        self.description = description
        self.age_rating = event_update.age_rating
        self._set_venue(event_update.venue)
        self._set_period(event_update.period)
        self._touch(now)
        self._record(
            EventUpdated(
                self.id,
                self.organization_id,
                self.title,
            )
        )

    def ensure_banner_image_change_allowed(self) -> None:
        if self.status not in _EDITABLE_STATUSES:
            raise InvalidStateTransition(f"A {self.status} event cannot change its banner image")

    def set_banner_image(self, object_key: str, now: datetime) -> None:
        self.ensure_banner_image_change_allowed()
        object_key = object_key.strip()
        if not object_key:
            raise InvalidValue("The banner image object key is required")
        if len(object_key) > BANNER_IMAGE_KEY_MAX_LENGTH:
            raise InvalidValue("The banner image object key is too long")

        self.banner_image_key = object_key
        self._touch(now)

    def change_venue(self, venue: Venue, now: datetime) -> None:
        """Buyers rely on the venue, so it is locked once the event is published."""
        if self.status != EventStatus.DRAFT:
            raise InvalidStateTransition("The venue can only be changed while the event is a draft")

        self._set_venue(venue)
        self._touch(now)

    def schedule(self, period: EventPeriod, now: datetime) -> None:
        """Once published, the period can only change through postpone()."""
        if self.status != EventStatus.DRAFT:
            raise InvalidStateTransition("A published event can only be rescheduled by postponing it")

        self._set_period(period)
        self._touch(now)

    def publish(self, now: datetime) -> None:
        if self.status != EventStatus.DRAFT:
            raise InvalidStateTransition(f"A {self.status} event cannot be published")
        if self.venue_data is None:
            raise InvalidStateTransition("The event needs a venue before being published")
        period = self.period
        if period is None:
            raise InvalidStateTransition("The event needs a period before being published")
        if period.has_started(now):
            raise InvalidStateTransition("An event that already started cannot be published")

        self.status = EventStatus.PUBLISHED
        self._touch(now)
        self._record(
            EventPublished(
                self.id,
                self.organization_id,
                self.title,
            )
        )

    def postpone(self, new_period: EventPeriod, now: datetime) -> None:
        if self.status not in _ON_SALE_STATUSES:
            raise InvalidStateTransition(f"A {self.status} event cannot be postponed")
        previous = self.period
        assert previous is not None  # guaranteed by publish()
        if new_period.has_started(now):
            raise InvalidStateTransition("The new period must be in the future")
        if new_period.start_at <= previous.start_at:
            raise InvalidStateTransition("The new period must start after the current one")

        self._set_period(new_period)
        self.status = EventStatus.POSTPONED
        self._touch(now)
        self._record(
            EventPostponed(
                event_id=self.id,
                organization_id=self.organization_id,
                start_at=new_period.start_at,
                end_at=new_period.end_at,
                previous_start_at=previous.start_at,
                previous_end_at=previous.end_at,
            )
        )

    def cancel(self, reason: str, now: datetime) -> None:
        if self.status not in _EDITABLE_STATUSES:
            raise InvalidStateTransition(f"A {self.status} event cannot be cancelled")

        reason = reason.strip()
        if not reason:
            raise InvalidValue("The cancellation reason is required")
        if len(reason) > CANCELLATION_REASON_MAX_LENGTH:
            raise InvalidValue(f"The cancellation reason must have at most {CANCELLATION_REASON_MAX_LENGTH} characters")

        was_public = self.status in _ON_SALE_STATUSES
        self.status = EventStatus.CANCELLED
        self.cancellation_reason = reason
        self._touch(now)

        # drafts were never visible to other contexts, so there is nothing to tell them
        if was_public:
            self._record(EventCancelled(event_id=self.id, organization_id=self.organization_id, reason=reason))

    def finish(self, now: datetime) -> None:
        if self.status not in _ON_SALE_STATUSES:
            raise InvalidStateTransition(f"A {self.status} event cannot be finished")
        period = self.period
        assert period is not None  # guaranteed by publish()
        if not period.has_ended(now):
            raise InvalidStateTransition("The event has not ended yet")

        self.status = EventStatus.FINISHED
        self._touch(now)
        self._record(EventFinished(event_id=self.id, organization_id=self.organization_id, end_at=period.end_at))

    def pull_events(self) -> list[PublishableEvent]:
        """Returns the events recorded since the last call and clears them."""
        events, self._pending_events = self._pending_events, []
        return events

    def _record(self, event: PublishableEvent) -> None:
        self._pending_events.append(event)

    def _touch(self, now: datetime) -> None:
        self.updated_at = now

    def _set_venue(self, venue: Venue | None) -> None:
        self.venue_data = _venue_to_dict(venue)

    def _set_period(self, period: EventPeriod | None) -> None:
        self.start_at = period.start_at if period else None
        self.end_at = period.end_at if period else None


def _validate_title(title: str) -> str:
    title = title.strip()
    if not title:
        raise InvalidValue("The title is required")
    if len(title) > TITLE_MAX_LENGTH:
        raise InvalidValue(f"The title must have at most {TITLE_MAX_LENGTH} characters")
    return title


def _validate_description(description: str) -> str:
    description = description.strip()
    if len(description) > DESCRIPTION_MAX_LENGTH:
        raise InvalidValue(f"The description must have at most {DESCRIPTION_MAX_LENGTH} characters")
    return description


def _venue_to_dict(venue: Venue | None) -> dict[str, Any] | None:
    match venue:
        case None:
            return None
        case OnlineVenue(url=url):
            return {"type": "online", "url": url}
        case PhysicalVenue(name=name, address=address):
            return {
                "type": "physical",
                "name": name,
                "address": {
                    "street": address.street,
                    "number": address.number,
                    "complement": address.complement,
                    "district": address.district,
                    "city": address.city,
                    "state": address.state,
                    "postal_code": address.postal_code,
                    "country": address.country,
                },
            }


def _venue_from_dict(data: dict[str, Any] | None) -> Venue | None:
    if data is None:
        return None
    if data["type"] == "online":
        return OnlineVenue(url=data["url"])
    return PhysicalVenue(name=data["name"], address=Address(**data["address"]))
