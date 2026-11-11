from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from events.domain.models.event.repository import EventRepository
from events.domain.models.event_view.event_view import (
    EventView,
)
from events.domain.models.event_view.repository import (
    EventViewRepository,
)
from shared.infra.database.sql import engine
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

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


async def test_record_batch_and_get_metrics(session: AsyncSession):
    event_repo = EventRepository(session)
    view_repo = EventViewRepository(session)

    # 1. Create and persist an event
    event = make_draft()
    await event_repo.save(event)

    # 2. Record batch of views
    today = datetime(2030, 1, 10, 10, 0, tzinfo=UTC)
    yesterday = today - timedelta(days=1)

    records = [
        EventView.record(
            event_id=event.id,
            visitor_hash="visitor_1",
            viewed_at=yesterday,
        ),
        EventView.record(
            event_id=event.id,
            visitor_hash="visitor_2",
            viewed_at=yesterday,
        ),
        EventView.record(
            event_id=event.id,
            visitor_hash="visitor_1",  # same visitor next day
            viewed_at=today,
        ),
        EventView.record(
            event_id=event.id,
            visitor_hash="visitor_3",
            viewed_at=today,
        ),
    ]

    await view_repo.record_batch(records)

    # 3. Retrieve metrics
    metrics = await view_repo.get_metrics(event.id, days=30, now=today)

    assert metrics.event_id == event.id
    assert metrics.total_views == 4
    assert metrics.unique_visitors == 3  # visitor_1, visitor_2, visitor_3
    assert len(metrics.daily_views) == 2

    # Yesterday
    assert metrics.daily_views[0].date == yesterday.date()
    assert metrics.daily_views[0].views == 2
    assert metrics.daily_views[0].unique_visitors == 2

    # Today
    assert metrics.daily_views[1].date == today.date()
    assert metrics.daily_views[1].views == 2
    assert metrics.daily_views[1].unique_visitors == 2
