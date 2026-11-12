from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response, status
from shared.infra.http.pagination import PaginatedOutput

from events.application.event.image import EventImageServiceDep, EventImageStorage
from events.application.event.service import EventServiceDep
from events.application.event.values import (
    PublicEventDetailsOutput,
    PublicEventListItemOutput,
)
from events.application.event_view.service import EventViewServiceDep
from events.domain.models.event.event import Event
from events.domain.models.event.values import EventID

router = APIRouter(prefix="/events", tags=["events", "public"])


def _get_banner_url(event: Event, image_service: EventImageStorage) -> str | None:
    return (
        image_service.public_url(event.banner_image_key)
        if event.banner_image_key
        else None
    )


def _public_output(
    event: Event, image_service: EventImageStorage
) -> PublicEventListItemOutput:
    return PublicEventListItemOutput.from_domain(
        event, banner_url=_get_banner_url(event, image_service)
    )


def _public_details_output(
    event: Event, image_service: EventImageStorage
) -> PublicEventDetailsOutput:
    return PublicEventDetailsOutput.from_domain(
        event, banner_url=_get_banner_url(event, image_service)
    )


@router.get("")
async def list_public_events(
    service: EventServiceDep,
    image_service: EventImageServiceDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedOutput[PublicEventListItemOutput]:
    response.headers["Cache-Control"] = "public, max-age=60, s-maxage=120"
    events, total = await service.list_public(limit=limit, offset=offset)
    return PaginatedOutput(
        items=[_public_output(event, image_service) for event in events],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{event_id}", response_model=PublicEventDetailsOutput)
async def get_public_event(
    event_id: EventID,
    service: EventServiceDep,
    image_service: EventImageServiceDep,
    response: Response,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> Response | PublicEventDetailsOutput:
    event = await service.get_public(event_id)
    etag = f'W/"{event.id}-{event.version}"'
    response.headers["Cache-Control"] = (
        "public, max-age=60, s-maxage=300, stale-while-revalidate=60"
    )
    response.headers["ETag"] = etag

    if if_none_match:
        client_etags = [tag.strip() for tag in if_none_match.split(",")]
        if etag in client_etags or "*" in client_etags:
            return Response(
                status_code=status.HTTP_304_NOT_MODIFIED,
                headers=dict(response.headers),
            )

    return _public_details_output(event, image_service)


@router.post("/{event_id}/views", status_code=status.HTTP_204_NO_CONTENT)
async def record_event_view(
    event_id: EventID,
    request: Request,
    service: EventViewServiceDep,
    session_token: Annotated[str | None, Header(alias="X-Session-ID")] = None,
) -> None:
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    await service.record_view(
        event_id=event_id,
        client_ip=client_ip,
        user_agent=user_agent,
        session_token=session_token,
    )
