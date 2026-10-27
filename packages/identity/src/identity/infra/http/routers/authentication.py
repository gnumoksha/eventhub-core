from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from shared.domain.errors import InvalidValue
from shared.settings import settings

from identity.application.authentication import (
    csrf_token,
)
from identity.domain.models.account.account import Account
from identity.domain.models.account.errors import (
    AuthenticationError,
    DuplicateAccountEmail,
    InvalidCredentialToken,
)
from identity.domain.models.values import Email, Password
from identity.infra.http.authentication import (
    AuthenticatedSessionDep,
    CSRFDep,
    IdentityServiceDep,
    TrustedOriginDep,
    session_cookie_name,
)

router = APIRouter(prefix="/identity", tags=["identity"])


class CredentialsInput(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=Password.MIN_LEN, max_length=Password.MAX_LEN)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        try:
            return Email(value).value
        except InvalidValue as exc:
            raise ValueError("Enter a valid email address") from exc

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        try:
            return Password(value).value
        except InvalidValue as exc:
            raise ValueError("Enter a valid password") from exc


class EmailInput(BaseModel):
    email: str = Field(max_length=320)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        try:
            return Email(value).value
        except InvalidValue as exc:
            raise ValueError("Enter a valid email address") from exc


class TokenInput(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class ResetPasswordInput(TokenInput):
    password: str = Field(min_length=Password.MIN_LEN, max_length=Password.MAX_LEN)


class ChangePasswordInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=Password.MIN_LEN, max_length=Password.MAX_LEN)


class AccountOutput(BaseModel):
    id: str
    email: str
    email_verified: bool


class SessionOutput(BaseModel):
    account: AccountOutput
    csrf_token: str


class MessageOutput(BaseModel):
    message: str


def _set_session_cookie(response: Response, token: str, expires_at: datetime) -> None:
    max_age = max(0, int((expires_at - datetime.now(UTC)).total_seconds()))
    response.set_cookie(
        key=session_cookie_name(),
        value=token,
        max_age=max_age,
        expires=max_age,
        httponly=True,
        secure=settings.is_prod_like(),
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=session_cookie_name(),
        httponly=True,
        secure=settings.is_prod_like(),
        samesite="lax",
        path="/",
    )


def _account_output(account: Account) -> AccountOutput:
    return AccountOutput(
        id=str(account.id),
        email=account.email,
        email_verified=account.email_verified_at is not None,
    )


def _csrf_for(token: str) -> str:
    return csrf_token(token, settings.APP_SECRET.get_secret_value())


@router.post("/signup", status_code=status.HTTP_202_ACCEPTED, response_model=MessageOutput)
async def signup(
    input_: CredentialsInput,
    response: Response,
    service: IdentityServiceDep,
    _origin: TrustedOriginDep,
) -> MessageOutput:
    try:
        _, session, raw_token = await service.signup(
            Email.from_trusted(input_.email),  # already validated on CredentialsInput
            Password.from_trusted(input_.password),  # already validated on CredentialsInput
        )
    except DuplicateAccountEmail:
        pass
    else:
        _set_session_cookie(response, raw_token, session.expires_at)
    # A new account gets a cookie; the response body never reveals whether the
    # normalized address already existed. The client fetches /identity/csrf.
    return MessageOutput(message="If the address can be registered, verification instructions will be sent")


@router.post("/login", response_model=SessionOutput)
async def login(
    input_: CredentialsInput,
    request: Request,
    response: Response,
    service: IdentityServiceDep,
    _origin: TrustedOriginDep,
) -> SessionOutput:
    client_ip = request.client.host if request.client else "unknown"
    try:
        account, session, raw_token = await service.login(
            Email.from_trusted(input_.email),  # already validated on CredentialsInput
            Password.from_trusted(input_.password),  # already validated on CredentialsInput
            client_ip,
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password") from exc

    _set_session_cookie(response, raw_token, session.expires_at)
    return SessionOutput(account=_account_output(account), csrf_token=_csrf_for(raw_token))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(auth: AuthenticatedSessionDep, service: IdentityServiceDep, _csrf: CSRFDep) -> Response:
    await service.logout(auth.session)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_session_cookie(response)
    return response


@router.get("/me", response_model=AccountOutput)
async def me(auth: AuthenticatedSessionDep) -> AccountOutput:
    return _account_output(auth.account)


@router.get("/csrf")
async def get_csrf(auth: AuthenticatedSessionDep, _origin: TrustedOriginDep) -> dict[str, str]:
    return {"csrf_token": _csrf_for(auth.raw_token)}


@router.post("/verify-email", response_model=MessageOutput)
async def verify_email(input_: TokenInput, service: IdentityServiceDep, _origin: TrustedOriginDep) -> MessageOutput:
    try:
        await service.verify_email(input_.token)
    except InvalidCredentialToken as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token") from exc
    return MessageOutput(message="Email verified")


@router.post("/verification-email", response_model=MessageOutput)
async def resend_verification(
    auth: AuthenticatedSessionDep,
    service: IdentityServiceDep,
    _csrf: CSRFDep,
) -> MessageOutput:
    await service.request_verification(Email(auth.account.email))
    return MessageOutput(message="If the account needs verification, an email will be sent")


@router.post("/password-reset", response_model=MessageOutput)
async def request_password_reset(
    input_: EmailInput,
    service: IdentityServiceDep,
    _origin: TrustedOriginDep,
) -> MessageOutput:
    await service.request_password_reset(Email(input_.email))
    return MessageOutput(message="If the account exists, a password reset email will be sent")


@router.post("/password-reset/confirm", response_model=MessageOutput)
async def confirm_password_reset(
    input_: ResetPasswordInput,
    service: IdentityServiceDep,
    _origin: TrustedOriginDep,
) -> MessageOutput:
    try:
        await service.reset_password(input_.token, input_.password)
    except InvalidCredentialToken as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token") from exc
    return MessageOutput(message="Password updated; please log in again")


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    input_: ChangePasswordInput,
    auth: AuthenticatedSessionDep,
    service: IdentityServiceDep,
    _csrf: CSRFDep,
) -> Response:
    try:
        await service.change_password(auth.account, input_.current_password, input_.password)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        ) from exc
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_session_cookie(response)
    return response
