import json
from datetime import datetime

from events.domain.models.event.repository import EventRepository, EventRepositoryDep
from events.domain.models.event.values import EventID
from events.domain.models.event_view.event_view import EventView
from events.domain.models.event_view.repository import EventViewRepository, EventViewRepositoryDep
from shared.infra.asyncio_ import run_coroutine
from shared.infra.database.memory import AsyncRedisDatabase, AsyncRedisDatabaseDep
from shared.infra.di import injectable
from shared.infra.logger import logger
from shared.infra.tasks import app

BUFFER_QUEUE_KEY = "events:views:pending"
FLUSH_SCHEDULED_KEY = "events:views:flush_scheduled"


async def _async_flush(
    redis: AsyncRedisDatabase,
    event_repo: EventRepository,
    event_view_repo: EventViewRepository,
    batch_size: int = 500,
) -> int:
    try:
        raw_items = await redis.list_pop(BUFFER_QUEUE_KEY, count=batch_size)
        if not raw_items:
            await redis.delete(FLUSH_SCHEDULED_KEY)
            return 0

        parsed_records: list[dict[str, str]] = []
        for raw in raw_items:
            try:
                parsed_records.append(json.loads(raw))
            except json.JSONDecodeError, TypeError:
                logger.warning(f"Failed to parse JSON for item: {raw}")
                continue

        if not parsed_records:
            await redis.delete(FLUSH_SCHEDULED_KEY)
            return 0

        event_ids = {EventID(rec["event_id"]) for rec in parsed_records if "event_id" in rec}
        valid_ids = await event_repo.find_ids_by_ids(event_ids)

        views: list[EventView] = [
            EventView.record(
                event_id=EventID(rec["event_id"]),
                visitor_hash=rec["visitor_hash"],
                viewed_at=datetime.fromisoformat(rec["viewed_at"]),
            )
            for rec in parsed_records
            if "event_id" in rec
            and "visitor_hash" in rec
            and "viewed_at" in rec
            and EventID(rec["event_id"]) in valid_ids
        ]

        if views:
            await event_view_repo.record_batch(views)

        await redis.delete(FLUSH_SCHEDULED_KEY)

        # If there are still items in the queue, schedule another batch
        remaining = await redis.list_length(BUFFER_QUEUE_KEY)
        if remaining > 0:
            flush_views_buffer.delay(batch_size=batch_size)

        return len(views)
    finally:
        await redis.aclose()


@app.task(name="events.flush_views_buffer")
@injectable
def flush_views_buffer(
    redis: AsyncRedisDatabaseDep,
    event_repo: EventRepositoryDep,
    event_view_repo: EventViewRepositoryDep,
    batch_size: int = 500,
) -> int:
    logger.info(f"Flushing event views buffer with batch size {batch_size}")
    return run_coroutine(
        _async_flush(
            redis,
            event_repo,
            event_view_repo,
            batch_size=batch_size,
        )
    )
