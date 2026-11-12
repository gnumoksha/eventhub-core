import uuid
from io import BytesIO
from typing import Annotated

from fastapi import (
    APIRouter,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from identity.infra.http.authentication import CommonSessionDep, CSRFDep
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
    UpdateEventInput,
)
from events.application.event_view.service import (
    EventViewServiceDep,
)
from events.domain.models.event.event import Event
from events.domain.models.event.values import EventID, EventStatus
from events.domain.models.event_view.values import EventViewsMetrics

router = APIRouter(prefix="/organizers/events", tags=["organizers", "events"])
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
    "",
    status_code=status.HTTP_201_CREATED,
)
async def create_event(
    event: Annotated[str, Form()],
    service: EventServiceDep,
    image_service: EventImageServiceDep,
    session: CommonSessionDep,
    _csrf: CSRFDep,
    banner: Annotated[UploadFile | None, File()] = None,
) -> EventOutput:
    try:
        input_ = CreateEventInput.model_validate_json(event)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    upload = await _read_banner(banner) if banner else None
    created = await service.create(
        organization_id=session.organization_id,
        title=input_.title,
        description=input_.description,
        age_rating=input_.age_rating,
        venue=input_.venue.to_domain() if input_.venue else None,
        period=input_.period.to_domain() if input_.period else None,
        banner=upload,
    )
    return _output(created, image_service)


@router.get("")
async def list_organization_events(
    service: EventServiceDep,
    image_service: EventImageServiceDep,
    session: CommonSessionDep,
    status_: Annotated[EventStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[EventOutput]:
    events = await service.list_by_organization(
        session.organization_id, status=status_, limit=limit, offset=offset
    )
    return [_output(event, image_service) for event in events]


@router.get("/{event_id}")
async def get_event(
    event_id: EventID, service: EventServiceDep, image_service: EventImageServiceDep
) -> EventOutput:
    return _output(await service.get(event_id), image_service)


@router.put("/{event_id}")
async def update_event(
    event_id: EventID,
    input_: UpdateEventInput,
    service: EventServiceDep,
    image_service: EventImageServiceDep,
    _session: CommonSessionDep,
    _csrf: CSRFDep,
) -> EventOutput:
    event = await service.update(event_id, input_.to_update())
    return _output(event, image_service)


@router.post("/{event_id}/publish")
async def publish_event(
    event_id: EventID,
    service: EventServiceDep,
    image_service: EventImageServiceDep,
    _session: CommonSessionDep,
    _csrf: CSRFDep,
) -> EventOutput:
    return _output(await service.publish(event_id), image_service)


@router.post("/{event_id}/postpone")
async def postpone_event(
    event_id: EventID,
    input_: PeriodSchema,
    service: EventServiceDep,
    image_service: EventImageServiceDep,
    _session: CommonSessionDep,
    _csrf: CSRFDep,
) -> EventOutput:
    return _output(await service.postpone(event_id, input_.to_domain()), image_service)


@router.post("/{event_id}/cancel")
async def cancel_event(
    event_id: EventID,
    input_: CancelEventInput,
    service: EventServiceDep,
    image_service: EventImageServiceDep,
    _session: CommonSessionDep,
    _csrf: CSRFDep,
) -> EventOutput:
    return _output(await service.cancel(event_id, input_.reason), image_service)


@router.put("/{event_id}/banner")
async def replace_event_banner(
    event_id: EventID,
    banner: Annotated[UploadFile, File()],
    service: EventServiceDep,
    image_service: EventImageServiceDep,
    _session: CommonSessionDep,
    _csrf: CSRFDep,
) -> EventOutput:
    upload = await _read_banner(banner)
    event = await service.update_banner(event_id, upload)
    return _output(event, image_service)


@router.post("/{event_id}/views", status_code=status.HTTP_204_NO_CONTENT)
async def record_event_view(
    event_id: uuid.UUID,
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


@router.get(
    "/{event_id}/views",
    response_model=EventViewsMetrics,
    status_code=status.HTTP_200_OK,
)
async def get_event_views(
    event_id: uuid.UUID,
    session: CommonSessionDep,
    event_service: EventServiceDep,
    view_service: EventViewServiceDep,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> EventViewsMetrics:
    event = await event_service.get(event_id)
    if event.organization_id != session.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to view metrics for this event",
        )
    return await view_service.get_event_metrics(event_id, days=days)
