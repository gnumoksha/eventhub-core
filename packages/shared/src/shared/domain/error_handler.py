from fastapi import Request, status
from fastapi.responses import JSONResponse

from shared.domain.errors import ConcurrencyConflict, DomainError, InvalidStateTransition, InvalidValue


def domain_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)

    status_code = {
        InvalidValue: status.HTTP_422_UNPROCESSABLE_CONTENT,
        InvalidStateTransition: status.HTTP_409_CONFLICT,
        ConcurrencyConflict: status.HTTP_409_CONFLICT,
    }.get(type(exc), status.HTTP_400_BAD_REQUEST)
    return JSONResponse(status_code=status_code, content={"detail": exc.message})
