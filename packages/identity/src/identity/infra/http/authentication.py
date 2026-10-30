import re
import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, HTTPException, Request, Security, status
from fastapi.security import APIKeyCookie
from shared.infra.di import Depends
from shared.settings import settings

from identity.application.authentication import IdentityServiceDep, verify_csrf_token
from identity.domain.models.account.account import Account, Session

SESSION_COOKIE = "__Host-eventhub_session"
DEV_SESSION_COOKIE = "eventhub_session"


def session_cookie_name() -> str:
    return SESSION_COOKIE if settings.is_prod_like() else DEV_SESSION_COOKIE


@dataclass(frozen=True)
class AuthenticatedSession:
    session: Session
    account: Account
    raw_token: str


session_cookie_scheme = APIKeyCookie(
    name=session_cookie_name(),
    scheme_name="SessionCookie",
    description="Opaque session cookie issued by the identity login endpoint.",
    auto_error=False,
)


async def require_session(
    token: Annotated[str | None, Security(session_cookie_scheme)],
    service: IdentityServiceDep,
) -> AuthenticatedSession:
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    authenticated = await service.authenticate_session(token)
    if authenticated is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    session, account = authenticated
    return AuthenticatedSession(session, account, token)


AuthenticatedSessionDep = Annotated[AuthenticatedSession, Depends(require_session)]


async def require_account_id(auth: AuthenticatedSessionDep) -> uuid.UUID:
    if auth.account.email_verified_at is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verify your email to access this resource")
    return auth.account.id


CurrentAccountID = Annotated[uuid.UUID, Depends(require_account_id)]


def _trusted_origin(origin: str | None) -> bool:
    if not origin:
        return False
    allowed = {value.strip().rstrip("/") for value in settings.CORS_ALLOWED_ORIGINS.split(",") if value.strip()}
    candidate = origin.rstrip("/")
    if candidate in allowed:
        return True
    pattern = settings.CORS_ALLOW_ORIGIN_REGEX
    return bool(pattern and re.fullmatch(pattern, candidate))


async def require_trusted_origin(origin: Annotated[str | None, Header()] = None) -> None:
    if not _trusted_origin(origin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Untrusted request origin")


TrustedOriginDep = Annotated[None, Depends(require_trusted_origin)]


async def require_csrf(
    request: Request,
    auth: AuthenticatedSessionDep,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    if not _trusted_origin(request.headers.get("origin")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Untrusted request origin")
    if not verify_csrf_token(auth.raw_token, settings.APP_SECRET.get_secret_value(), csrf_header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


CSRFDep = Annotated[None, Depends(require_csrf)]
