"""
Publishes the integration events stored in the transactional outbox.

Run it with: uv run python -m bin.outbox_relay

Many instances can run at the same time: each message is locked while it is published.
"""

import asyncio
import signal
from types import FrameType

import checkin
import events
import finance
import identity
import notifications
import organizers
import payments
import reporting
import sales
import ticketing
from libs.events import load_events
from shared.infra.database import SessionDep
from shared.infra.di import injectable
from shared.infra.domain_events import QueueDispatcherDep
from shared.infra.logger import logger
from shared.infra.observability.sentry import initialize_sentry
from shared.infra.outbox import OutboxRelay

CONTEXTS = [checkin, events, finance, identity, notifications, organizers, payments, reporting, sales, ticketing]
IDLE_SLEEP_SECONDS = 1.0

initialize_sentry()


class _StopSignal:
    def __init__(self) -> None:
        self.received = False
        signal.signal(signal.SIGINT, self._handle)
        signal.signal(signal.SIGTERM, self._handle)

    def _handle(self, signum: int, _frame: FrameType | None) -> None:
        logger.info("Received signal %s, stopping the outbox relay", signum)
        self.received = True


@injectable
async def main(dispatcher: QueueDispatcherDep, session: SessionDep) -> None:
    # the relay rebuilds the events from the outbox, so it must know every event class
    for context in CONTEXTS:
        load_events(context)

    stop = _StopSignal()
    logger.info("Outbox relay started")

    relay = OutboxRelay(session, dispatcher)
    while not stop.received:
        published = await relay.relay()

        # nothing pending or the broker is down: wait before polling again
        if published == 0:
            await asyncio.sleep(IDLE_SLEEP_SECONDS)

    logger.info("Outbox relay stopped")


if __name__ == "__main__":
    asyncio.run(main())  # ty:ignore[missing-argument]
