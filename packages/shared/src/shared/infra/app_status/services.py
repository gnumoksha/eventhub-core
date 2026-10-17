from collections.abc import Awaitable, Callable
from timeit import default_timer as timer
from typing import Annotated, Any

from shared.infra.app_status.inputs import ShowAppStatusInput
from shared.infra.app_status.outputs import (
    AppOutput,
    ShowAppStatusOutput,
)
from shared.infra.database import SessionDep
from shared.infra.di import Depends
from shared.settings import Settings, SettingsDep
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class AppStatusService:
    def __init__(self, settings: Settings, session: AsyncSession):
        self.settings = settings
        self.session = session

    async def execute(self, _input: ShowAppStatusInput) -> ShowAppStatusOutput:
        global_success = True
        tested_services = await self.__test_services(_input.mode)
        for service in tested_services.values():
            if not service["success"]:
                global_success = False
                break

        return ShowAppStatusOutput(
            success=global_success,
            app=AppOutput(env=self.settings.APP_ENV, version=self.settings.APP_VERSION),
            services=tested_services or None,
        )

    async def __test_services(self, mode: str) -> dict[str, Any]:
        if mode != "full":
            return {}

        return {"database": await self.__test_service(lambda: self.session.execute(text("SELECT 1")))}

    async def __test_service(self, func: Callable[[], Awaitable[Any]]) -> dict[str, Any]:
        success = True
        exception = None
        start = timer()

        try:
            await func()
        except Exception as e:  # noqa: BLE001
            success = False
            exception = str(e)

        return {
            "success": success,
            "exception": exception,
            "duration": timer() - start,
        }


async def __get_app_status_service(
    settings: SettingsDep,
    session: SessionDep,
) -> AppStatusService:
    return AppStatusService(settings, session)


AppStatusServiceDep = Annotated[AppStatusService, Depends(__get_app_status_service)]
