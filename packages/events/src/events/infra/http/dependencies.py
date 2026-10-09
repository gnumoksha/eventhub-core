from typing import Annotated

from shared.infra.database import SessionDep
from shared.infra.di import Depends

from events.application.event.service import EventService
from events.infra.persistence.sql_event_repository import SqlEventRepository


def get_event_service(session: SessionDep) -> EventService:
    return EventService(SqlEventRepository(session))


EventServiceDep = Annotated[EventService, Depends(get_event_service)]
