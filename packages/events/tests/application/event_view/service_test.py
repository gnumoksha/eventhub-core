import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from events.application.event_view.service import (
    BUFFER_THRESHOLD,
    COUNTDOWN_SECONDS,
    DEDUPLICATION_TTL_SECONDS,
    EventViewService,
)
from events.domain.models.event_view.values import (
    DailyViews,
    EventViewsMetrics,
)


@pytest.mark.asyncio
async def test_record_view_new_visitor_enqueues_and_schedules_flush():
    repository = AsyncMock()
    redis = AsyncMock()
    # is_new = True
    redis.set.side_effect = ["1", "1"]  # seen_key success, schedule flush success
    redis.rpush.return_value = 1  # 1 item in queue

    service = EventViewService(repository, redis)
    event_id = uuid.uuid4()

    with patch("events.application.event_view.service.flush_views_buffer.apply_async") as mock_apply_async:
        recorded = await service.record_view(
            event_id=event_id,
            client_ip="192.168.1.1",
            user_agent="Mozilla/5.0",
            session_token="anon-token-123",  # noqa: S106
        )

        assert recorded is True
        assert redis.set.call_count == 2
        # Check deduplication call
        first_call = redis.set.call_args_list[0]
        assert first_call[0][0].startswith(f"views:seen:{event_id}:")
        assert first_call[1]["ex"] == DEDUPLICATION_TTL_SECONDS
        assert first_call[1]["nx"] is True

        # Check queue push
        assert redis.rpush.call_count == 1
        assert redis.rpush.call_args[0][0] == "events:views:pending"

        # Check flush scheduled with countdown
        mock_apply_async.assert_called_once_with(countdown=COUNTDOWN_SECONDS)


@pytest.mark.asyncio
async def test_record_view_duplicate_visitor_is_ignored():
    repository = AsyncMock()
    redis = AsyncMock()
    # is_new = None (key already existed in Redis)
    redis.set.return_value = None

    service = EventViewService(repository, redis)
    event_id = uuid.uuid4()

    recorded = await service.record_view(
        event_id=event_id,
        client_ip="192.168.1.1",
        user_agent="Mozilla/5.0",
    )

    assert recorded is False
    redis.rpush.assert_not_called()


@pytest.mark.asyncio
async def test_record_view_triggers_immediate_flush_when_threshold_reached():
    repository = AsyncMock()
    redis = AsyncMock()
    redis.set.return_value = "1"
    redis.rpush.return_value = BUFFER_THRESHOLD  # 100 items

    service = EventViewService(repository, redis)
    event_id = uuid.uuid4()

    with patch("events.application.event_view.service.flush_views_buffer.delay") as mock_delay:
        recorded = await service.record_view(
            event_id=event_id,
            client_ip="192.168.1.1",
            user_agent="Mozilla/5.0",
        )

        assert recorded is True
        mock_delay.assert_called_once()


@pytest.mark.asyncio
async def test_get_event_metrics_uses_cache():
    repository = AsyncMock()
    redis = AsyncMock()
    event_id = uuid.uuid4()

    cached_metrics = EventViewsMetrics(
        event_id=event_id,
        total_views=10,
        unique_visitors=8,
        daily_views=[
            DailyViews(
                date=date(2030, 1, 1),
                views=10,
                unique_visitors=8,
            )
        ],
    )
    redis.get.return_value = cached_metrics.model_dump_json()

    service = EventViewService(repository, redis)
    result = await service.get_event_metrics(event_id)

    assert result == cached_metrics
    repository.get_metrics.assert_not_called()


@pytest.mark.asyncio
async def test_get_event_metrics_queries_repository_and_populates_cache():
    repository = AsyncMock()
    redis = AsyncMock()
    event_id = uuid.uuid4()

    redis.get.return_value = None  # Cache miss

    db_metrics = EventViewsMetrics(
        event_id=event_id,
        total_views=15,
        unique_visitors=12,
        daily_views=[],
    )
    repository.get_metrics.return_value = db_metrics

    service = EventViewService(repository, redis)
    result = await service.get_event_metrics(event_id)

    assert result == db_metrics
    repository.get_metrics.assert_called_once_with(event_id, days=30)
    redis.set.assert_called_once_with(
        f"events:views:metrics:{event_id}:30",
        db_metrics.model_dump_json(),
        ex=300,
    )
