from shared.infra.database import get_static_session
from shared.infra.logger import logger
from shared.infra.tasks import app

from events.application.event.service import EventService
from events.infra.persistence.sql_event_repository import SqlEventRepository


# TODO schedule it periodically with Celery beat
@app.task
def finish_ended_events() -> int:
    with get_static_session() as session:
        service = EventService(SqlEventRepository(session))
        finished = service.finish_ended_events()

    logger.info("Finished %d ended events", finished)
    return finished
