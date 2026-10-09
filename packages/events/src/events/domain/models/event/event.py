# The Event aggregate root

from datetime import datetime
from typing import Self

import uuid_utils.compat as uuid_compat
from libs.events import PublishableEvent

from events.domain.errors import InvalidStateTransition, InvalidValue
from events.domain.models.event.events import EventCancelled, EventFinished, EventPostponed, EventPublished
from events.domain.models.event.values import (
    AgeRating,
    EventID,
    EventPeriod,
    EventStatus,
    OrganizationID,
    Venue,
)

TITLE_MAX_LENGTH = 100
DESCRIPTION_MAX_LENGTH = 10_000
CANCELLATION_REASON_MAX_LENGTH = 500

_EDITABLE_STATUSES = (EventStatus.DRAFT, EventStatus.PUBLISHED, EventStatus.POSTPONED)
_ON_SALE_STATUSES = (EventStatus.PUBLISHED, EventStatus.POSTPONED)


class Event:
    """
    The event as a product: what happens, where and when.

    Ticket types, batches and prices do not live here; they belong to Sales.

    Lifecycle: Draft -> Published -> (Postponed) -> Cancelled | Finished
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        id: EventID,
        organization_id: OrganizationID,
        title: str,
        description: str,
        age_rating: AgeRating,
        status: EventStatus,
        venue: Venue | None,
        period: EventPeriod | None,
        cancellation_reason: str | None,
        created_at: datetime,
        updated_at: datetime,
        version: int,
    ) -> None:
        """Rebuilds an existing event. Use Event.create() to create a new one."""
        self.id = id
        self.organization_id = organization_id
        self._title = title
        self._description = description
        self._age_rating = age_rating
        self._status = status
        self._venue = venue
        self._period = period
        self._cancellation_reason = cancellation_reason
        self.created_at = created_at
        self.updated_at = updated_at
        self.version = version
        self._pending_events: list[PublishableEvent] = []

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
        return cls(
            id=uuid_compat.uuid7(),
            organization_id=organization_id,
            title=_validate_title(title),
            description=_validate_description(description),
            age_rating=age_rating,
            status=EventStatus.DRAFT,
            venue=venue,
            period=period,
            cancellation_reason=None,
            created_at=now,
            updated_at=now,
            version=0,
        )

    @property
    def title(self) -> str:
        return self._title

    @property
    def description(self) -> str:
        return self._description

    @property
    def age_rating(self) -> AgeRating:
        return self._age_rating

    @property
    def status(self) -> EventStatus:
        return self._status

    @property
    def venue(self) -> Venue | None:
        return self._venue

    @property
    def period(self) -> EventPeriod | None:
        return self._period

    @property
    def cancellation_reason(self) -> str | None:
        return self._cancellation_reason

    def update_details(self, *, title: str, description: str, age_rating: AgeRating, now: datetime) -> None:
        if self._status not in _EDITABLE_STATUSES:
            raise InvalidStateTransition(f"A {self._status} event cannot be edited")

        self._title = _validate_title(title)
        self._description = _validate_description(description)
        self._age_rating = age_rating
        self._touch(now)

    def change_venue(self, venue: Venue, now: datetime) -> None:
        """Buyers rely on the venue, so it is locked once the event is published."""
        if self._status != EventStatus.DRAFT:
            raise InvalidStateTransition("The venue can only be changed while the event is a draft")

        self._venue = venue
        self._touch(now)

    def schedule(self, period: EventPeriod, now: datetime) -> None:
        """Once published, the period can only change through postpone()."""
        if self._status != EventStatus.DRAFT:
            raise InvalidStateTransition("A published event can only be rescheduled by postponing it")

        self._period = period
        self._touch(now)

    def publish(self, now: datetime) -> None:
        if self._status != EventStatus.DRAFT:
            raise InvalidStateTransition(f"A {self._status} event cannot be published")
        if self._venue is None:
            raise InvalidStateTransition("The event needs a venue before being published")
        if self._period is None:
            raise InvalidStateTransition("The event needs a period before being published")
        if self._period.has_started(now):
            raise InvalidStateTransition("An event that already started cannot be published")

        self._status = EventStatus.PUBLISHED
        self._touch(now)
        self._record(
            EventPublished(
                event_id=self.id,
                organization_id=self.organization_id,
                title=self._title,
                start_at=self._period.start_at,
                end_at=self._period.end_at,
            )
        )

    def postpone(self, new_period: EventPeriod, now: datetime) -> None:
        if self._status not in _ON_SALE_STATUSES:
            raise InvalidStateTransition(f"A {self._status} event cannot be postponed")
        assert self._period is not None  # guaranteed by publish()
        if new_period.has_started(now):
            raise InvalidStateTransition("The new period must be in the future")
        if new_period.start_at <= self._period.start_at:
            raise InvalidStateTransition("The new period must start after the current one")

        previous = self._period
        self._period = new_period
        self._status = EventStatus.POSTPONED
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
        if self._status not in _EDITABLE_STATUSES:
            raise InvalidStateTransition(f"A {self._status} event cannot be cancelled")

        reason = reason.strip()
        if not reason:
            raise InvalidValue("The cancellation reason is required")
        if len(reason) > CANCELLATION_REASON_MAX_LENGTH:
            raise InvalidValue(f"The cancellation reason must have at most {CANCELLATION_REASON_MAX_LENGTH} characters")

        was_public = self._status in _ON_SALE_STATUSES
        self._status = EventStatus.CANCELLED
        self._cancellation_reason = reason
        self._touch(now)

        # drafts were never visible to other contexts, so there is nothing to tell them
        if was_public:
            self._record(EventCancelled(event_id=self.id, organization_id=self.organization_id, reason=reason))

    def finish(self, now: datetime) -> None:
        if self._status not in _ON_SALE_STATUSES:
            raise InvalidStateTransition(f"A {self._status} event cannot be finished")
        assert self._period is not None  # guaranteed by publish()
        if not self._period.has_ended(now):
            raise InvalidStateTransition("The event has not ended yet")

        self._status = EventStatus.FINISHED
        self._touch(now)
        self._record(EventFinished(event_id=self.id, organization_id=self.organization_id, end_at=self._period.end_at))

    def pull_events(self) -> list[PublishableEvent]:
        """Returns the events recorded since the last call and clears them."""
        events, self._pending_events = self._pending_events, []
        return events

    def _record(self, event: PublishableEvent) -> None:
        self._pending_events.append(event)

    def _touch(self, now: datetime) -> None:
        self.updated_at = now


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
