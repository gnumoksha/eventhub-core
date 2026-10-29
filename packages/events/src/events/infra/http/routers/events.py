import uuid
from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from identity.infra.http.authentication import CSRFDep, CurrentAccountID
from pydantic import ValidationError

from events.application.event.image import (
    EventBannerUpload,
    EventImageServiceDep,
    EventImageStorage,
)
from events.application.event.service import EventServiceDep
from events.application.event.values import (
    CancelEventInput,
    CreateEventInput,
    EventOutput,
    PeriodSchema,
    UpdateEventDetailsInput,
    VenueSchema,
)
from events.domain.models.event.event import Event
from events.domain.models.event.values import EventID, EventStatus

router = APIRouter(tags=["events"])
# TODO authorize that the authenticated account belongs to the event's organization.

MAX_BANNER_SIZE = 5 * 1024 * 1024
_BANNER_FORMATS = {
    "image/jpeg": ("jpg", b"\xff\xd8\xff"),
    "image/png": ("png", b"\x89PNG\r\n\x1a\n"),
    "image/webp": ("webp", b"RIFF"),
}


def _output(event: Event, image_service: EventImageStorage) -> EventOutput:
    banner_url = (
        image_service.public_url(event.banner_image_key)
        if event.banner_image_key
        else None
    )
    return EventOutput.from_domain(event, banner_url=banner_url)


async def _read_banner(file: UploadFile) -> EventBannerUpload:
    content_type = (file.content_type or "").lower()
    fmt = _BANNER_FORMATS.get(content_type)
    if fmt is None:
        raise HTTPException(status_code=415, detail="Banner must be JPEG, PNG, or WebP")

    content = await file.read(MAX_BANNER_SIZE + 1)
    if len(content) > MAX_BANNER_SIZE:
        raise HTTPException(status_code=413, detail="Banner must be at most 5 MiB")

    extension, signature = fmt
    if not content.startswith(signature) or (
        content_type == "image/webp" and content[8:12] != b"WEBP"
    ):
        raise HTTPException(
            status_code=415, detail="Banner content does not match its image type"
        )

    return EventBannerUpload(BytesIO(content), content_type, extension)


@router.post(
    "/organizations/{organization_id}/events",
    status_code=status.HTTP_201_CREATED,
)
async def create_event(
    organization_id: uuid.UUID,
    event: Annotated[str, Form()],
    service: EventServiceDep,
    image_service: EventImageServiceDep,
    _account_id: CurrentAccountID,
    _csrf: CSRFDep,
    banner: Annotated[UploadFile | None, File()] = None,
) -> EventOutput:
    try:
        input_ = CreateEventInput.model_validate_json(event)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    upload = await _read_banner(banner) if banner else None
    created = await service.create(
        organization_id=organization_id,
        title=input_.title,
        description=input_.description,
        age_rating=input_.age_rating,
        venue=input_.venue.to_domain() if input_.venue else None,
        period=input_.period.to_domain() if input_.period else None,
        banner=upload,
    )
    return _output(created, image_service)


@router.get("/organizations/{organization_id}/events")
async def list_organization_events(
    organization_id: uuid.UUID,
    service: EventServiceDep,
    image_service: EventImageServiceDep,
    status_: Annotated[EventStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[EventOutput]:
    events = await service.list_by_organization(
        organization_id, status=status_, limit=limit, offset=offset
    )
    return [_output(event, image_service) for event in events]


@router.get("/events/{event_id}")
async def get_event(
    event_id: EventID, service: EventServiceDep, image_service: EventImageServiceDep
) -> EventOutput:
    return _output(await service.get(event_id), image_service)


@router.put("/events/{event_id}/details")
async def update_event_details(
    event_id: EventID,
    input_: UpdateEventDetailsInput,
    service: EventServiceDep,
    image_service: EventImageServiceDep,
    _account_id: CurrentAccountID,
    _csrf: CSRFDep,
) -> EventOutput:
    event = await service.update_details(
        event_id,
        title=input_.title,
        description=input_.description,
        age_rating=input_.age_rating,
    )
    return _output(event, image_service)


@router.put("/events/{event_id}/venue")
async def change_event_venue(
    event_id: EventID,
    input_: VenueSchema,
    service: EventServiceDep,
    image_service: EventImageServiceDep,
    _account_id: CurrentAccountID,
    _csrf: CSRFDep,
) -> EventOutput:
    return _output(
        await service.change_venue(event_id, input_.to_domain()), image_service
    )


@router.put("/events/{event_id}/period")
async def schedule_event(
    event_id: EventID,
    input_: PeriodSchema,
    service: EventServiceDep,
    image_service: EventImageServiceDep,
    _account_id: CurrentAccountID,
    _csrf: CSRFDep,
) -> EventOutput:
    return _output(await service.schedule(event_id, input_.to_domain()), image_service)


@router.post("/events/{event_id}/publish")
async def publish_event(
    event_id: EventID,
    service: EventServiceDep,
    image_service: EventImageServiceDep,
    _account_id: CurrentAccountID,
    _csrf: CSRFDep,
) -> EventOutput:
    return _output(await service.publish(event_id), image_service)


@router.post("/events/{event_id}/postpone")
async def postpone_event(
    event_id: EventID,
    input_: PeriodSchema,
    service: EventServiceDep,
    image_service: EventImageServiceDep,
    _account_id: CurrentAccountID,
    _csrf: CSRFDep,
) -> EventOutput:
    return _output(await service.postpone(event_id, input_.to_domain()), image_service)


@router.post("/events/{event_id}/cancel")
async def cancel_event(
    event_id: EventID,
    input_: CancelEventInput,
    service: EventServiceDep,
    image_service: EventImageServiceDep,
    _account_id: CurrentAccountID,
    _csrf: CSRFDep,
) -> EventOutput:
    return _output(await service.cancel(event_id, input_.reason), image_service)


@router.put("/events/{event_id}/banner")
async def replace_event_banner(
    event_id: EventID,
    banner: Annotated[UploadFile, File()],
    service: EventServiceDep,
    image_service: EventImageServiceDep,
    _account_id: CurrentAccountID,
    _csrf: CSRFDep,
) -> EventOutput:
    upload = await _read_banner(banner)
    event = await service.update_banner(event_id, upload)
    return _output(event, image_service)
