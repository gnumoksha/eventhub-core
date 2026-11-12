from typing import Annotated

from fastapi import APIRouter, Query
from shared.infra.http.pagination import PaginatedOutput

from events.application.event.image import EventImageServiceDep, EventImageStorage
from events.application.event.service import EventServiceDep
from events.application.event.values import PublicEventListItemOutput
from events.domain.models.event.event import Event

router = APIRouter(prefix="/events", tags=["events", "public"])


def _public_output(
    event: Event, image_service: EventImageStorage
) -> PublicEventListItemOutput:
    banner_url = (
        image_service.public_url(event.banner_image_key)
        if event.banner_image_key
        else None
    )
    return PublicEventListItemOutput.from_domain(event, banner_url=banner_url)


@router.get("")
async def list_public_events(
    service: EventServiceDep,
    image_service: EventImageServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedOutput[PublicEventListItemOutput]:
    events, total = await service.list_public(limit=limit, offset=offset)
    return PaginatedOutput(
        items=[_public_output(event, image_service) for event in events],
        total=total,
        limit=limit,
        offset=offset,
    )
