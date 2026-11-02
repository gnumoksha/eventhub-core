from fastapi import Request, status
from fastapi.responses import JSONResponse

from shared.domain.errors import (
    AccessDenied,
    ConcurrencyConflict,
    DomainError,
    EntityNotFound,
    InvalidStateTransition,
    InvalidValue,
)


def domain_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)

    status_codes = {
        InvalidValue: status.HTTP_422_UNPROCESSABLE_CONTENT,
        EntityNotFound: status.HTTP_404_NOT_FOUND,
        AccessDenied: status.HTTP_403_FORBIDDEN,
        InvalidStateTransition: status.HTTP_409_CONFLICT,
        ConcurrencyConflict: status.HTTP_409_CONFLICT,
    }
    status_code = next(
        (code for error_type, code in status_codes.items() if isinstance(exc, error_type)),
        status.HTTP_400_BAD_REQUEST,
    )
    return JSONResponse(status_code=status_code, content={"detail": exc.message})
