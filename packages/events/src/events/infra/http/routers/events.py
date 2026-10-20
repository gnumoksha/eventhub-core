import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from identity.infra.http.authentication import CSRFDep, CurrentAccountID

from events.application.event.service import EventServiceDep
from events.application.event.values import (
    CancelEventInput,
    CreateEventInput,
    EventOutput,
    PeriodSchema,
    UpdateEventDetailsInput,
    VenueSchema,
)
from events.domain.models.event.values import EventID, EventStatus

router = APIRouter(tags=["events"])
# TODO authorize that the authenticated account belongs to the event's organization.


@router.post("/organizations/{organization_id}/events", status_code=status.HTTP_201_CREATED)
async def create_event(
    organization_id: uuid.UUID,
    input_: CreateEventInput,
    service: EventServiceDep,
    _account_id: CurrentAccountID,
    _csrf: CSRFDep,
) -> EventOutput:
    event = await service.create(
        organization_id=organization_id,
        title=input_.title,
        description=input_.description,
        age_rating=input_.age_rating,
        venue=input_.venue.to_domain() if input_.venue else None,
        period=input_.period.to_domain() if input_.period else None,
    )
    return EventOutput.from_domain(event)


@router.get("/organizations/{organization_id}/events")
async def list_organization_events(
    organization_id: uuid.UUID,
    service: EventServiceDep,
    status_: Annotated[EventStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[EventOutput]:
    events = await service.list_by_organization(organization_id, status=status_, limit=limit, offset=offset)
    return [EventOutput.from_domain(event) for event in events]


@router.get("/events/{event_id}")
async def get_event(event_id: EventID, service: EventServiceDep) -> EventOutput:
    return EventOutput.from_domain(await service.get(event_id))


@router.put("/events/{event_id}/details")
async def update_event_details(
    event_id: EventID,
    input_: UpdateEventDetailsInput,
    service: EventServiceDep,
    _account_id: CurrentAccountID,
    _csrf: CSRFDep,
) -> EventOutput:
    event = await service.update_details(
        event_id,
        title=input_.title,
        description=input_.description,
        age_rating=input_.age_rating,
    )
    return EventOutput.from_domain(event)


@router.put("/events/{event_id}/venue")
async def change_event_venue(
    event_id: EventID,
    input_: VenueSchema,
    service: EventServiceDep,
    _account_id: CurrentAccountID,
    _csrf: CSRFDep,
) -> EventOutput:
    return EventOutput.from_domain(await service.change_venue(event_id, input_.to_domain()))


@router.put("/events/{event_id}/period")
async def schedule_event(
    event_id: EventID,
    input_: PeriodSchema,
    service: EventServiceDep,
    _account_id: CurrentAccountID,
    _csrf: CSRFDep,
) -> EventOutput:
    return EventOutput.from_domain(await service.schedule(event_id, input_.to_domain()))


@router.post("/events/{event_id}/publish")
async def publish_event(
    event_id: EventID,
    service: EventServiceDep,
    _account_id: CurrentAccountID,
    _csrf: CSRFDep,
) -> EventOutput:
    return EventOutput.from_domain(await service.publish(event_id))


@router.post("/events/{event_id}/postpone")
async def postpone_event(
    event_id: EventID,
    input_: PeriodSchema,
    service: EventServiceDep,
    _account_id: CurrentAccountID,
    _csrf: CSRFDep,
) -> EventOutput:
    return EventOutput.from_domain(await service.postpone(event_id, input_.to_domain()))


@router.post("/events/{event_id}/cancel")
async def cancel_event(
    event_id: EventID,
    input_: CancelEventInput,
    service: EventServiceDep,
    _account_id: CurrentAccountID,
    _csrf: CSRFDep,
) -> EventOutput:
    return EventOutput.from_domain(await service.cancel(event_id, input_.reason))
