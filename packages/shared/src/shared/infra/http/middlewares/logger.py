from shared.infra.logger import logger
from shared.settings import settings
from starlette.middleware.base import BaseHTTPMiddleware


class LogMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log incoming requests and outgoing responses as json.

    Reference:
    https://github.com/sheshbabu/fastapi-structured-json-logging-demo/blob/0ee5f2def471dac94f653951f66bfbea5b81364b/src/log_middleware.py
    """

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if settings.APP_DEBUG:
            logger.info(
                "Incoming request",
                extra={
                    "request": {"method": request.method, "url": str(request.url)},
                    "response": {
                        "status_code": response.status_code,
                    },
                },
            )
        return response
