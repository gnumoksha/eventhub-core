from typing import Annotated

from libs.time_utils import Clock, utc_now
from shared.infra.di import Depends
from shared.infra.logger import logger

from events.application.event.image import EventBannerUpload, EventImageServiceDep, EventImageStorage
from events.domain.models.event.event import Event
from events.domain.models.event.repository import EventRepository, EventRepositoryDep
from events.domain.models.event.values import (
    AgeRating,
    EventID,
    EventPeriod,
    EventStatus,
    EventUpdate,
    OrganizationID,
    Venue,
)


class EventNotFound(Exception):
    def __init__(self, event_id: EventID) -> None:
        super().__init__(f"Event {event_id} not found")
        self.event_id = event_id


class EventService:
    """Use cases of Event Management."""

    def __init__(
        self,
        repository: EventRepository,
        image_service: EventImageStorage,
        clock: Clock = utc_now,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._image_service = image_service

    async def create(  # noqa: PLR0913
        self,
        *,
        organization_id: OrganizationID,
        title: str,
        description: str,
        age_rating: AgeRating,
        venue: Venue | None = None,
        period: EventPeriod | None = None,
        banner: EventBannerUpload | None = None,
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
        if banner:
            image_service = self._image_service
            object_key = image_service.new_object_key(event.id, banner.extension)
            image_service.public_url(object_key)
            try:
                await image_service.upload(banner.image, object_key, content_type=banner.content_type)
                event.set_banner_image(object_key, self._clock())
                await self._repository.save(event)
            except Exception:
                await self._delete_quietly(object_key)
                raise
        else:
            await self._repository.save(event)
        return event

    async def update_banner(self, event_id: EventID, banner: EventBannerUpload) -> Event:
        event = await self.get(event_id)
        event.ensure_banner_image_change_allowed()

        image_service = self._image_service
        object_key = image_service.new_object_key(event.id, banner.extension)
        image_service.public_url(object_key)
        old_key = event.banner_image_key
        try:
            await image_service.upload(banner.image, object_key, content_type=banner.content_type)
            event.set_banner_image(object_key, self._clock())
            await self._repository.save(event)
        except Exception:
            await self._delete_quietly(object_key)
            raise
        if old_key:
            await self._delete_quietly(old_key)
        return event

    async def _delete_quietly(self, object_key: str) -> None:
        try:
            await self._image_service.delete(object_key)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to clean up event image", extra={"object_key": object_key})

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
        return await self._repository.list_by_organization(
            organization_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def update(self, event_id: EventID, event_update: EventUpdate) -> Event:
        event = await self.get(event_id)

        event.update(event_update, now=self._clock())

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


async def __get_service(
    repo: EventRepositoryDep,
    image_service: EventImageServiceDep,
) -> EventService:
    return EventService(
        repo,
        image_service=image_service,
    )


EventServiceDep = Annotated[EventService, Depends(__get_service)]
