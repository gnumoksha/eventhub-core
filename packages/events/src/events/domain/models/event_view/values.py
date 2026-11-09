from datetime import date

from pydantic import BaseModel, ConfigDict

from events.domain.models.event.values import EventID


class DailyViews(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    views: int
    unique_visitors: int


class EventViewsMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: EventID
    total_views: int
    unique_visitors: int
    daily_views: list[DailyViews]
