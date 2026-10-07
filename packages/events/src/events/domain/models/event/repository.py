from typing import Annotated

from fastapi import Depends
from shared.infra.database import SessionDep
from sqlmodel import Session

from events.domain.models.event.entity import Event, EventID


class EventRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, entity: Event) -> Event:
        self.session.add(entity)
        self.session.commit()
        self.session.refresh(entity)  # Refresh to get the generated IDs

        return entity

    def find_by_id(self, id: EventID) -> Event | None:
        return self.session.get(Event, id)


def __get_event_repository(session: SessionDep) -> EventRepository:
    return EventRepository(session)


EventRepositoryDep = Annotated[EventRepository, Depends(__get_event_repository)]
