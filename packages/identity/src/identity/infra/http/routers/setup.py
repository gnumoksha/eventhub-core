from fastapi import FastAPI

from identity.infra.http.routers.authentication import router as authentication_router


def setup_routers(app: FastAPI) -> None:
    app.include_router(authentication_router)
