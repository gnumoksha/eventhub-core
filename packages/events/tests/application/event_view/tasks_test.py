import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
import pytest_asyncio
from events.application.event_view.tasks import (
    BUFFER_QUEUE_KEY,
    FLUSH_SCHEDULED_KEY,
    _async_flush,
    flush_views_buffer,
)
from events.domain.models.event.repository import EventRepository
from events.domain.models.event_view.repository import (
    EventViewRepository,
)
from redis.asyncio import Redis
from shared.infra.database.memory import AsyncRedisDatabase
from shared.infra.database.sql import engine
from shared.settings import settings
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
)

from tests.conftest import make_draft

pytestmark = [pytest.mark.database_access, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def connection() -> AsyncIterator[AsyncConnection]:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        yield connection
        await transaction.rollback()
    await engine.dispose()


def open_session(connection: AsyncConnection) -> AsyncSession:
    return AsyncSession(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )


@pytest_asyncio.fixture
async def session(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    async with open_session(connection) as session:
        yield session


async def test_async_flush_processes_valid_events_and_discards_invalid_and_malformed(
    session: AsyncSession,
):
    event_repo = EventRepository(session)
    view_repo = EventViewRepository(session)

    # 1. Create a real event in the database
    event = make_draft()
    await event_repo.save(event)

    invalid_event_id = uuid.uuid4()

    # 2. Setup Redis with items in buffer
    client = Redis.from_url(settings.REDIS_DSN, decode_responses=True)
    redis = AsyncRedisDatabase(client, app_env=settings.APP_ENV)
    await redis.delete(BUFFER_QUEUE_KEY, FLUSH_SCHEDULED_KEY)

    valid_payload = json.dumps(
        {
            "event_id": str(event.id),
            "visitor_hash": "hash_1",
            "viewed_at": datetime.now(UTC).isoformat(),
        }
    )
    invalid_payload = json.dumps(
        {
            "event_id": str(invalid_event_id),
            "visitor_hash": "hash_2",
            "viewed_at": datetime.now(UTC).isoformat(),
        }
    )
    malformed_uuid_payload = json.dumps(
        {
            "event_id": "not-a-valid-uuid",
            "visitor_hash": "hash_3",
            "viewed_at": datetime.now(UTC).isoformat(),
        }
    )
    malformed_json = "{bad-json"

    await redis.list_push(
        BUFFER_QUEUE_KEY,
        valid_payload,
        invalid_payload,
        malformed_uuid_payload,
        malformed_json,
    )
    await redis.set(FLUSH_SCHEDULED_KEY, "1")

    try:
        # 3. Run flush passing dependencies
        flushed_count = await _async_flush(
            redis=redis,
            event_repo=event_repo,
            event_view_repo=view_repo,
            batch_size=10,
        )

        assert flushed_count == 1  # Only the valid event
        assert await redis.list_length(BUFFER_QUEUE_KEY) == 0
        assert await redis.get(FLUSH_SCHEDULED_KEY) is None

        # Check DB
        metrics = await view_repo.get_metrics(event.id)
        assert metrics.total_views == 1
        assert metrics.unique_visitors == 1
    finally:
        await redis.delete(BUFFER_QUEUE_KEY, FLUSH_SCHEDULED_KEY)
        await client.aclose()


async def test_flush_views_buffer_task_delegates_to_async_flush():
    def _fake_run(coro):
        coro.close()
        return 42

    with patch(
        "events.application.event_view.tasks.run_coroutine",
        side_effect=_fake_run,
    ) as mock_run_coroutine:
        result = flush_views_buffer(batch_size=25)

        assert result == 42
        mock_run_coroutine.assert_called_once()
