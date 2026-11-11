import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated

from events.application.event_view.tasks import (
    BUFFER_QUEUE_KEY,
    FLUSH_SCHEDULED_KEY,
    flush_views_buffer,
)
from events.domain.models.event.values import EventID
from events.domain.models.event_view.repository import (
    EventViewRepository,
    EventViewRepositoryDep,
)
from events.domain.models.event_view.values import EventViewsMetrics
from shared.infra.database.memory import (
    AsyncCache,
    AsyncCacheDep,
    AsyncList,
    AsyncListDep,
)
from shared.infra.di import Depends

CACHE_TTL_SECONDS = 300  # 5 minutes
DEDUPLICATION_TTL_SECONDS = 3600  # 1 hour
BUFFER_THRESHOLD = 100
COUNTDOWN_SECONDS = 60


def compute_visitor_hash(
    client_ip: str | None,
    user_agent: str | None,
    session_token: str | None = None,
) -> str:
    raw = f"{client_ip or ''}|{user_agent or ''}|{session_token or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class EventViewService:
    def __init__(
        self,
        repository: EventViewRepository,
        cache: AsyncCache,
        distributed_list: AsyncList,
    ) -> None:
        self._repository = repository
        self._cache = cache
        self._distributed_list = distributed_list

    async def record_view(
        self,
        *,
        event_id: EventID,
        client_ip: str | None,
        user_agent: str | None,
        session_token: str | None = None,
    ) -> bool:
        visitor_hash = compute_visitor_hash(client_ip, user_agent, session_token)
        seen_key = f"views:seen:{event_id}:{visitor_hash}"

        # Deduplication: return False if viewed in the last hour
        is_new = await self._cache.set_nx(seen_key, "1", ex=DEDUPLICATION_TTL_SECONDS)
        if not is_new:
            return False

        payload = json.dumps(
            {
                "event_id": str(event_id),
                "visitor_hash": visitor_hash,
                "viewed_at": datetime.now(UTC).isoformat(),
            }
        )
        queue_len = await self._distributed_list.list_push(BUFFER_QUEUE_KEY, payload)

        # Buffer flush triggers
        if queue_len >= BUFFER_THRESHOLD:
            flush_views_buffer.delay()
        else:
            scheduled = await self._cache.set_nx(FLUSH_SCHEDULED_KEY, "1", ex=COUNTDOWN_SECONDS)
            if scheduled:
                flush_views_buffer.apply_async(countdown=COUNTDOWN_SECONDS)

        return True

    async def get_event_metrics(
        self,
        event_id: EventID,
        *,
        days: int = 30,
    ) -> EventViewsMetrics:
        cache_key = f"events:views:metrics:{event_id}:{days}"
        cached = await self._cache.get(cache_key)
        if cached:
            return EventViewsMetrics.model_validate_json(cached)

        metrics = await self._repository.get_metrics(event_id, days=days)
        await self._cache.set(cache_key, metrics.model_dump_json(), expiration=CACHE_TTL_SECONDS)
        return metrics


def get_event_view_service(
    repository: EventViewRepositoryDep,
    cache: AsyncCacheDep,
    distributed_list: AsyncListDep,
) -> EventViewService:
    return EventViewService(repository, cache, distributed_list)


EventViewServiceDep = Annotated[EventViewService, Depends(get_event_view_service)]
