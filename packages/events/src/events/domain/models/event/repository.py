from datetime import datetime
from typing import Annotated

from shared.domain.errors import ConcurrencyConflict
from shared.infra.database import SessionDep
from shared.infra.di import Depends
from shared.infra.outbox import add_to_outbox
from sqlalchemy.orm.exc import StaleDataError
from sqlmodel import Session, col, select

from events.domain.models.event.event import Event
from events.domain.models.event.values import EventID, EventStatus, OrganizationID


class EventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, id: EventID) -> Event | None:
        return self._session.get(Event, id)

    def save(self, event: Event) -> None:
        """
        Inserts or updates the event and, in the same transaction, stores its
        pending integration events to be published.

        Raises:
            ConcurrencyConflict: if the event was modified since it was loaded.
        """
        event_id = event.id  # read before a rollback expires the object, which would reload it from the database
        self._session.add(event)
        # same transaction as the aggregate: the events are published if, and only if, the change is committed
        add_to_outbox(self._session, event.pull_events())

        try:
            self._session.commit()
        except StaleDataError as exc:
            self._session.rollback()
            raise ConcurrencyConflict(f"Event {event_id} was modified by someone else") from exc

    def list_by_organization(
        self,
        organization_id: OrganizationID,
        *,
        status: EventStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Event]:
        query = select(Event).where(Event.organization_id == organization_id)
        if status is not None:
            query = query.where(Event.status == status)
        query = query.order_by(col(Event.start_at).desc().nulls_first(), col(Event.id).desc())

        return list(self._session.exec(query.offset(offset).limit(limit)).all())

    def list_ended_but_not_finished(self, now: datetime, *, limit: int) -> list[Event]:
        """Returns published or postponed events whose period already ended."""
        query = (
            select(Event)
            .where(
                col(Event.status).in_([EventStatus.PUBLISHED, EventStatus.POSTPONED]),
                col(Event.end_at) <= now,
            )
            .order_by(col(Event.end_at))
            .limit(limit)
        )
        return list(self._session.exec(query).all())


def __get_repository(session: SessionDep) -> EventRepository:
    return EventRepository(session)


EventRepositoryDep = Annotated[EventRepository, Depends(__get_repository)]
