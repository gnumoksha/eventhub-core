from typing import Annotated

from libs.time_utils import Clock, utc_now
from shared.infra.di import Depends

from events.domain.models.event.event import Event
from events.domain.models.event.repository import EventRepository, EventRepositoryDep
from events.domain.models.event.values import AgeRating, EventID, EventPeriod, EventStatus, OrganizationID, Venue


class EventNotFound(Exception):
    def __init__(self, event_id: EventID) -> None:
        super().__init__(f"Event {event_id} not found")
        self.event_id = event_id


class EventService:
    """Use cases of Event Management."""

    def __init__(self, repository: EventRepository, clock: Clock = utc_now) -> None:
        self._repository = repository
        self._clock = clock

    async def create(  # noqa: PLR0913
        self,
        *,
        organization_id: OrganizationID,
        title: str,
        description: str,
        age_rating: AgeRating,
        venue: Venue | None = None,
        period: EventPeriod | None = None,
    ) -> Event:
        event = Event.create(
            organization_id=organization_id,
            title=title,
            description=description,
            age_rating=age_rating,
            venue=venue,
            period=period,
            now=self._clock(),
        )
        await self._repository.save(event)
        return event

    async def get(self, event_id: EventID) -> Event:
        event = await self._repository.get(event_id)
        if event is None:
            raise EventNotFound(event_id)
        return event

    async def list_by_organization(
        self,
        organization_id: OrganizationID,
        *,
        status: EventStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Event]:
        return await self._repository.list_by_organization(organization_id, status=status, limit=limit, offset=offset)

    async def update_details(self, event_id: EventID, *, title: str, description: str, age_rating: AgeRating) -> Event:
        event = await self.get(event_id)
        event.update_details(title=title, description=description, age_rating=age_rating, now=self._clock())
        await self._repository.save(event)
        return event

    async def change_venue(self, event_id: EventID, venue: Venue) -> Event:
        event = await self.get(event_id)
        event.change_venue(venue, self._clock())
        await self._repository.save(event)
        return event

    async def schedule(self, event_id: EventID, period: EventPeriod) -> Event:
        event = await self.get(event_id)
        event.schedule(period, self._clock())
        await self._repository.save(event)
        return event

    async def publish(self, event_id: EventID) -> Event:
        event = await self.get(event_id)
        event.publish(self._clock())
        await self._repository.save(event)
        return event

    async def postpone(self, event_id: EventID, new_period: EventPeriod) -> Event:
        event = await self.get(event_id)
        event.postpone(new_period, self._clock())
        await self._repository.save(event)
        return event

    async def cancel(self, event_id: EventID, reason: str) -> Event:
        event = await self.get(event_id)
        event.cancel(reason, self._clock())
        await self._repository.save(event)
        return event

    async def finish_ended_events(self, *, batch_size: int = 100) -> int:
        """Finishes every event whose period already ended. Returns how many were finished."""
        now = self._clock()
        events = await self._repository.list_ended_but_not_finished(now, limit=batch_size)
        for event in events:
            event.finish(now)
            await self._repository.save(event)
        return len(events)


async def __get_service(repo: EventRepositoryDep) -> EventService:
    return EventService(repo)


EventServiceDep = Annotated[EventService, Depends(__get_service)]
