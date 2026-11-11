import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from shared.infra.database.sql import SessionDep
from shared.infra.di import Depends
from sqlalchemy import Date, cast
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, func, select

from events.domain.models.event_view.event_view import EventView
from events.domain.models.event_view.values import (
    DailyViews,
    EventViewsMetrics,
)


class EventViewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_batch(self, views: list[EventView]) -> None:
        if not views:
            return
        self._session.add_all(views)
        await self._session.commit()

    async def get_metrics(
        self,
        event_id: uuid.UUID,
        *,
        days: int = 30,
        now: datetime | None = None,
    ) -> EventViewsMetrics:
        current_time = now if now is not None else datetime.now(UTC)
        since = current_time - timedelta(days=days)

        summary_query = select(
            func.count(col(EventView.id)).label("total_views"),
            func.count(func.distinct(col(EventView.visitor_hash))).label("unique_visitors"),
        ).where(
            EventView.event_id == event_id,
            col(EventView.viewed_at) >= since,
        )
        summary_res = await self._session.execute(summary_query)
        summary_row = summary_res.first()
        total_views = int(summary_row[0]) if summary_row and summary_row[0] is not None else 0
        unique_visitors = int(summary_row[1]) if summary_row and summary_row[1] is not None else 0

        date_col = cast(col(EventView.viewed_at), Date).label("view_date")
        daily_query = (
            select(
                date_col,
                func.count(col(EventView.id)).label("views"),
                func.count(func.distinct(col(EventView.visitor_hash))).label("unique_visitors"),
            )
            .where(
                EventView.event_id == event_id,
                col(EventView.viewed_at) >= since,
            )
            .group_by(date_col)
            .order_by(date_col)
        )
        daily_res = await self._session.execute(daily_query)
        daily_rows = daily_res.all()

        daily_views = [
            DailyViews(
                date=row[0] if isinstance(row[0], date) else date.fromisoformat(str(row[0])),
                views=int(row[1]),
                unique_visitors=int(row[2]),
            )
            for row in daily_rows
        ]

        return EventViewsMetrics(
            event_id=event_id,
            total_views=total_views,
            unique_visitors=unique_visitors,
            daily_views=daily_views,
        )


def get_event_view_repository(
    session: SessionDep,
) -> EventViewRepository:
    return EventViewRepository(session)


EventViewRepositoryDep = Annotated[EventViewRepository, Depends(get_event_view_repository)]
