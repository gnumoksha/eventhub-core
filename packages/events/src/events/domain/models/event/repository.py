from datetime import datetime
from typing import Any

from shared.domain.errors import ConcurrencyConflict
from shared.infra.outbox import add_to_outbox
from sqlmodel import Session, col, select, update

from events.domain.models.event.event import Event
from events.domain.models.event.values import (
    Address,
    AgeRating,
    EventID,
    EventPeriod,
    EventStatus,
    OnlineVenue,
    OrganizationID,
    PhysicalVenue,
    Venue,
)
from events.infra.persistence.event_record import EventRecord


class EventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, id: EventID) -> Event | None:
        record = self._session.get(EventRecord, id)
        return _to_domain(record) if record else None

    def save(self, event: Event) -> None:
        """
        Inserts or updates the event and, in the same transaction, stores its
        pending integration events to be published.

        Raises:
            ConcurrencyConflict: if the event was modified since it was loaded.
        """
        values = _to_record_values(event)

        if event.version == 0:
            self._session.add(EventRecord(**values, version=1))
        else:
            # optimistic locking: only update the row if nobody changed it since it was loaded
            result = self._session.exec(
                update(EventRecord)
                .where(col(EventRecord.id) == event.id, col(EventRecord.version) == event.version)
                .values(**values, version=event.version + 1)
            )
            if result.rowcount == 0:
                self._session.rollback()
                raise ConcurrencyConflict(f"Event {event.id} was modified by someone else")

        # same transaction as the aggregate: the events are published if, and only if, the change is committed
        add_to_outbox(self._session, event.pull_events())
        self._session.commit()
        self._session.expire_all()
        event.version += 1

    def list_by_organization(
        self,
        organization_id: OrganizationID,
        *,
        status: EventStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Event]:
        query = select(EventRecord).where(EventRecord.organization_id == organization_id)
        if status is not None:
            query = query.where(EventRecord.status == status.value)
        query = query.order_by(col(EventRecord.start_at).desc().nulls_first(), col(EventRecord.id).desc())

        records = self._session.exec(query.offset(offset).limit(limit)).all()
        return [_to_domain(record) for record in records]

    def list_ended_but_not_finished(self, now: datetime, *, limit: int) -> list[Event]:
        """Returns published or postponed events whose period already ended."""
        query = (
            select(EventRecord)
            .where(
                col(EventRecord.status).in_([EventStatus.PUBLISHED.value, EventStatus.POSTPONED.value]),
                col(EventRecord.end_at) <= now,
            )
            .order_by(col(EventRecord.end_at))
            .limit(limit)
        )
        return [_to_domain(record) for record in self._session.exec(query).all()]


def _to_record_values(event: Event) -> dict[str, Any]:
    return {
        "id": event.id,
        "organization_id": event.organization_id,
        "title": event.title,
        "description": event.description,
        "age_rating": event.age_rating.value,
        "status": event.status.value,
        "venue": _venue_to_dict(event.venue),
        "start_at": event.period.start_at if event.period else None,
        "end_at": event.period.end_at if event.period else None,
        "cancellation_reason": event.cancellation_reason,
        "created_at": event.created_at,
        "updated_at": event.updated_at,
    }


def _to_domain(record: EventRecord) -> Event:
    period = None
    if record.start_at is not None and record.end_at is not None:
        period = EventPeriod(start_at=record.start_at, end_at=record.end_at)

    return Event(
        id=record.id,
        organization_id=record.organization_id,
        title=record.title,
        description=record.description,
        age_rating=AgeRating(record.age_rating),
        status=EventStatus(record.status),
        venue=_venue_from_dict(record.venue),
        period=period,
        cancellation_reason=record.cancellation_reason,
        created_at=record.created_at,
        updated_at=record.updated_at,
        version=record.version,
    )


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
