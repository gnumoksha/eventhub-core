from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from events.application.event.service import EventNotFound
from events.infra.http.routers.organizers.events import (
    router as organizers_events_router,
)


def setup_routers(app: FastAPI) -> None:
    app.include_router(organizers_events_router)

    app.add_exception_handler(EventNotFound, _event_not_found_handler)


def _event_not_found_handler(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)}
    )
