import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from identity.infra.http.authentication import CommonSessionDep

from events.application.event.service import EventServiceDep
from events.application.event_view.service import (
    EventViewServiceDep,
)
from events.domain.models.event_view.values import EventViewsMetrics

router = APIRouter(prefix="/events", tags=["events"])


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
