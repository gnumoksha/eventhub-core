from fastapi import FastAPI
from shared.domain.error_handler import domain_error_handler
from shared.domain.errors import DomainError

from identity.infra.http.routers.authentication import router as authentication_router


def setup_routers(app: FastAPI) -> None:
    app.include_router(authentication_router)

    app.add_exception_handler(DomainError, domain_error_handler)
