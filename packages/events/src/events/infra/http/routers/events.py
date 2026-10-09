import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from events.domain.models.event.values import EventID, EventStatus
from events.infra.http.dependencies import EventServiceDep
from events.infra.http.schemas import (
    CancelEventInput,
    CreateEventInput,
    EventOutput,
    PeriodSchema,
    UpdateEventDetailsInput,
    VenueSchema,
)

# TODO require authentication and check that the account is a member of the event's organization
router = APIRouter(tags=["events"])


@router.post("/organizations/{organization_id}/events", status_code=status.HTTP_201_CREATED)
def create_event(organization_id: uuid.UUID, input_: CreateEventInput, service: EventServiceDep) -> EventOutput:
    event = service.create(
        organization_id=organization_id,
        title=input_.title,
        description=input_.description,
        age_rating=input_.age_rating,
        venue=input_.venue.to_domain() if input_.venue else None,
        period=input_.period.to_domain() if input_.period else None,
    )
    return EventOutput.from_domain(event)


@router.get("/organizations/{organization_id}/events")
def list_organization_events(
    organization_id: uuid.UUID,
    service: EventServiceDep,
    status_: Annotated[EventStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[EventOutput]:
    events = service.list_by_organization(organization_id, status=status_, limit=limit, offset=offset)
    return [EventOutput.from_domain(event) for event in events]


@router.get("/events/{event_id}")
def get_event(event_id: EventID, service: EventServiceDep) -> EventOutput:
    return EventOutput.from_domain(service.get(event_id))


@router.put("/events/{event_id}/details")
def update_event_details(event_id: EventID, input_: UpdateEventDetailsInput, service: EventServiceDep) -> EventOutput:
    event = service.update_details(
        event_id,
        title=input_.title,
        description=input_.description,
        age_rating=input_.age_rating,
    )
    return EventOutput.from_domain(event)


@router.put("/events/{event_id}/venue")
def change_event_venue(event_id: EventID, input_: VenueSchema, service: EventServiceDep) -> EventOutput:
    return EventOutput.from_domain(service.change_venue(event_id, input_.to_domain()))


@router.put("/events/{event_id}/period")
def schedule_event(event_id: EventID, input_: PeriodSchema, service: EventServiceDep) -> EventOutput:
    return EventOutput.from_domain(service.schedule(event_id, input_.to_domain()))


@router.post("/events/{event_id}/publish")
def publish_event(event_id: EventID, service: EventServiceDep) -> EventOutput:
    return EventOutput.from_domain(service.publish(event_id))


@router.post("/events/{event_id}/postpone")
def postpone_event(event_id: EventID, input_: PeriodSchema, service: EventServiceDep) -> EventOutput:
    return EventOutput.from_domain(service.postpone(event_id, input_.to_domain()))


@router.post("/events/{event_id}/cancel")
def cancel_event(event_id: EventID, input_: CancelEventInput, service: EventServiceDep) -> EventOutput:
    return EventOutput.from_domain(service.cancel(event_id, input_.reason))
