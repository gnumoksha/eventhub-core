from typing import Any

import checkin.application
import events.application
import finance.application
import identity.application
import notifications.application
import organizers.application
import payments.application
import reporting.application
import sales.application
import ticketing.application
from checkin.infra.http.routers.setup import setup_routers as checkin_setup_routers
from events.infra.http.routers.setup import setup_routers as events_setup_routers
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from finance.infra.http.routers.setup import setup_routers as finance_setup_routers
from identity.infra.http.routers.setup import setup_routers as identity_setup_routers
from libs.events import load_listeners
from notifications.infra.http.routers.setup import setup_routers as notifications_setup_routers
from organizers.infra.http.routers.setup import setup_routers as organizers_setup_routers
from payments.infra.http.routers.setup import setup_routers as payments_setup_routers
from reporting.infra.http.routers.setup import setup_routers as reporting_setup_routers
from sales.infra.http.routers.setup import setup_routers as sales_setup_routers
from shared.infra.app_status.inputs import Mode, ShowAppStatusInput
from shared.infra.app_status.outputs import ShowAppStatusOutput
from shared.infra.app_status.services import AppStatusServiceDep
from shared.infra.authentication.ip import require_private_ip_address
from shared.infra.di import Depends
from shared.infra.http.middlewares.logger import LogMiddleware
from shared.infra.logger import logger
from shared.infra.observability.sentry import initialize_sentry
from shared.settings import settings
from starlette.middleware.sessions import SessionMiddleware
from ticketing.infra.http.routers.setup import setup_routers as ticketing_setup_routers


def traces_sampler(sampling_context: dict[str, Any]) -> float:
    transaction_context = sampling_context.get("transaction_context") or {}
    name = transaction_context.get("name")

    if name and "/app-status" in name:
        return 0.0

    parent_sampling_decision = sampling_context.get("parent_sampled")
    if parent_sampling_decision is not None:
        return float(parent_sampling_decision)

    return 1.0


initialize_sentry(include_http_integrations=True, traces_sampler=traces_sampler)

app = FastAPI(
    title="Eventhub - core",
    description="A hub for your events",
    version=settings.APP_VERSION,
    openapi_url=None if settings.is_prod() else "/openapi.json",
    debug=settings.APP_DEBUG,
)

if settings.is_prod():
    # only in production because during development it is hard to read in the console
    app.add_middleware(LogMiddleware)
app.add_middleware(SessionMiddleware, secret_key=settings.APP_SECRET.get_secret_value())
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x for x in settings.CORS_ALLOWED_ORIGINS.split(",") if x],
    allow_origin_regex=settings.CORS_ALLOW_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=("*"),
    allow_headers=("*"),
)


@app.exception_handler(500)
async def http_exception_handler(request: Request, exc: Exception):  # noqa: ARG001
    import traceback  # noqa: PLC0415

    from fastapi.responses import JSONResponse  # noqa: PLC0415

    msg = "Internal server error"

    if settings.is_dev_like():
        msg = str(exc)
        logger.error(
            "Error %s %s ",
            str(exc),
            list(traceback.TracebackException.from_exception(exc).format()),
        )

    return JSONResponse(
        status_code=500,
        content={
            "detail": msg,
        },
    )


@app.get("/app-status", dependencies=[Depends(require_private_ip_address)])
async def app_status(
    service: AppStatusServiceDep,
    mode: Mode | None = Query("common"),
) -> ShowAppStatusOutput:
    input_ = ShowAppStatusInput(mode=mode or "common")
    return await service.execute(input_)


identity_setup_routers(app)
load_listeners(identity.application)

organizers_setup_routers(app)
load_listeners(organizers.application)

events_setup_routers(app)
load_listeners(events.application)

sales_setup_routers(app)
load_listeners(sales.application)

payments_setup_routers(app)
load_listeners(payments.application)

ticketing_setup_routers(app)
load_listeners(ticketing.application)

checkin_setup_routers(app)
load_listeners(checkin.application)

finance_setup_routers(app)
load_listeners(finance.application)

notifications_setup_routers(app)
load_listeners(notifications.application)

reporting_setup_routers(app)
load_listeners(reporting.application)
