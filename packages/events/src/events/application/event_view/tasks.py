import json
from datetime import datetime

from events.domain.models.event.repository import (
    EventRepositoryDep,
)
from events.domain.models.event.values import EventID
from events.domain.models.event_view.event_view import EventView
from events.domain.models.event_view.repository import (
    EventViewRepositoryDep,
)
from shared.infra.asyncio_ import run_coroutine
from shared.infra.database.memory import (
    AsyncRedisDatabaseDep,
)
from shared.infra.di import injectable
from shared.infra.logger import logger
from shared.infra.tasks import app

BUFFER_QUEUE_KEY = "events:views:pending"
FLUSH_SCHEDULED_KEY = "events:views:flush_scheduled"


def _parse_raw_items(raw_items: list[str]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for raw in raw_items:
        try:
            records.append(json.loads(raw))
        except json.JSONDecodeError, TypeError:
            logger.warning(f"Failed to parse JSON for item: {raw}")
    return records


def _extract_event_ids(records: list[dict[str, str]]) -> set[EventID]:
    ids: set[EventID] = set()
    for rec in records:
        if "event_id" in rec:
            try:
                ids.add(EventID(rec["event_id"]))
            except ValueError, TypeError:
                logger.warning(f"Invalid event_id in record: {rec['event_id']}")
                continue
    return ids


def _build_views(records: list[dict[str, str]], valid_ids: set[EventID]) -> list[EventView]:
    views: list[EventView] = []
    for rec in records:
        if not ("event_id" in rec and "visitor_hash" in rec and "viewed_at" in rec):
            logger.warning(f"Missing required fields in record: {rec}")
            continue
        try:
            eid = EventID(rec["event_id"])
            viewed_at = datetime.fromisoformat(rec["viewed_at"])
        except ValueError, TypeError:
            logger.warning(f"Invalid viewed_at in record: {rec['viewed_at']}")
            continue

        if eid in valid_ids:
            views.append(
                EventView.record(
                    event_id=eid,
                    visitor_hash=rec["visitor_hash"],
                    viewed_at=viewed_at,
                )
            )
    return views


@injectable
async def _async_flush(
    redis: AsyncRedisDatabaseDep,
    event_repo: EventRepositoryDep,
    event_view_repo: EventViewRepositoryDep,
    batch_size: int = 500,
) -> int:
    raw_items = await redis.list_pop(BUFFER_QUEUE_KEY, count=batch_size)
    if not raw_items:
        await redis.delete(FLUSH_SCHEDULED_KEY)
        return 0

    parsed_records = _parse_raw_items(raw_items)
    if not parsed_records:
        await redis.delete(FLUSH_SCHEDULED_KEY)
        return 0

    event_ids = _extract_event_ids(parsed_records)
    valid_ids = await event_repo.find_ids_by_ids(event_ids)
    views = _build_views(parsed_records, valid_ids)

    if views:
        await event_view_repo.record_batch(views)

    await redis.delete(FLUSH_SCHEDULED_KEY)

    # If there are still items in the queue, schedule another batch
    remaining = await redis.list_length(BUFFER_QUEUE_KEY)
    if remaining > 0:
        flush_views_buffer.delay(batch_size=batch_size)

    return len(views)


@app.task(name="events.flush_views_buffer")
def flush_views_buffer(
    batch_size: int = 500,
) -> int:
    logger.info(f"Flushing event views buffer with batch size {batch_size}")
    return run_coroutine(_async_flush(batch_size=batch_size))  # ty: ignore[missing-argument]
