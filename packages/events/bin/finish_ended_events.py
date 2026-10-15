import time

from events.application.event.service import EventServiceDep
from shared.infra.di import injectable
from shared.infra.logger import logger


@injectable
def main(service: EventServiceDep):
    start = time.perf_counter()
    logger.info("finish_ended_events: started")

    finished = service.finish_ended_events()

    duration = time.perf_counter() - start
    logger.info(f"finish_ended_events: completed in {duration:.1f}s, {finished} events")


if __name__ == "__main__":
    main()
