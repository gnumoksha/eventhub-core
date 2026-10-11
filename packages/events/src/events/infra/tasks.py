from shared.infra.database import get_static_session
from shared.infra.logger import logger
from shared.infra.tasks import app

from events.application.event.service import EventService
from events.domain.models.event.repository import EventRepository


# TODO schedule it periodically with Celery beat
# TODO use injectable
@app.task
def finish_ended_events() -> int:
    with get_static_session() as session:
        service = EventService(EventRepository(session))
        finished = service.finish_ended_events()

    logger.info("Finished %d ended events", finished)
    return finished
