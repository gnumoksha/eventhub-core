from typing import Annotated

from shared.infra.database import SessionDep
from shared.infra.di import Depends

from events.application.event.service import EventService
from events.domain.models.event.repository import EventRepository


def get_event_service(session: SessionDep) -> EventService:
    return EventService(EventRepository(session))


EventServiceDep = Annotated[EventService, Depends(get_event_service)]
