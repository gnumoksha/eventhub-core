from fastapi import FastAPI

from organizers.infra.http.routers.organizations import router as organizations_router


def setup_routers(app: FastAPI) -> None:
    app.include_router(organizations_router)
