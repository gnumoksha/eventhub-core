import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.concurrency import run_in_threadpool
from pwdlib import PasswordHash
from redis.asyncio import Redis
from shared.infra.authentication.token_encryption import encrypt_authentication_token
from sqlalchemy.exc import IntegrityError

from identity.domain.models.account.account import Account, AccountCredential, CredentialPurpose, Session
from identity.domain.models.account.events import AccountLoggedIn, AccountVerificationRequested, PasswordResetRequested
from identity.domain.models.account.repository import AccountRepository
from identity.domain.models.values import Email, Password

SESSION_LIFETIME = timedelta(days=7)
VERIFICATION_LIFETIME = timedelta(hours=24)
PASSWORD_RESET_LIFETIME = timedelta(hours=1)
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_BACKOFF_SECONDS = 15 * 60
LOGIN_FAILURE_LIMIT = 3
password_hash = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = password_hash.hash("eventhub-dummy-password")


class AuthenticationError(Exception):
    pass


class InvalidCredentialToken(Exception):
    pass


class DuplicateAccountEmail(Exception):
    pass


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_token() -> str:
    return secrets.token_urlsafe(32)


class LoginThrottle:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @staticmethod
    def _key(email: Email, client_ip: str) -> str:
        key_material = f"{email.value}\x00{client_ip}".encode()
        return f"identity:login:{hashlib.sha256(key_material).hexdigest()}"

    async def check(self, email: Email, client_ip: str) -> None:
        if await self._redis.ttl(f"{self._key(email, client_ip)}:blocked") > 0:
            raise AuthenticationError

    async def failed(self, email: Email, client_ip: str) -> None:
        key = self._key(email, client_ip)
        failures = await self._redis.incr(f"{key}:failures")
        if failures == 1:
            await self._redis.expire(f"{key}:failures", LOGIN_WINDOW_SECONDS)
        if failures >= LOGIN_FAILURE_LIMIT:
            await self._redis.set(f"{key}:blocked", "1", ex=LOGIN_BACKOFF_SECONDS)

    async def succeeded(self, email: Email, client_ip: str) -> None:
        key = self._key(email, client_ip)
        await self._redis.delete(f"{key}:failures", f"{key}:blocked")


class IdentityService:
    def __init__(self, repository: AccountRepository, redis: Redis) -> None:
        self._repository = repository
        self._throttle = LoginThrottle(redis)

    async def signup(
        self,
        email: Email,
        password: Password,
        *,
        now: datetime | None = None,
    ) -> tuple[Account, Session, str]:
        now = now or datetime.now(UTC)
        # Password hashing and verification are synchronous and CPU-bound, so offload them to keep the async event loop responsive.
        hashed = await run_in_threadpool(password_hash.hash, password.value)
        account = Account(email=email.value, password_hash=hashed)
        self._repository.add(account)
        try:
            await self._repository.flush()
        except IntegrityError as exc:
            await self._repository.rollback()
            constraint_name = getattr(exc.orig, "constraint_name", None) or getattr(
                getattr(exc.orig, "diag", None), "constraint_name", None
            )
            if constraint_name == "uq_identity_accounts_email":
                raise DuplicateAccountEmail from exc
            raise

        token = _new_token()
        credential = AccountCredential(
            account_id=account.id,
            purpose=CredentialPurpose.EMAIL_VERIFICATION.value,
            token_hash=_token_hash(token),
            expires_at=now + VERIFICATION_LIFETIME,
        )
        session, raw_session_token = self._new_session(account.id, now)
        await self._repository.save(
            credential,
            session,
            events=[
                AccountVerificationRequested(account.email, encrypt_authentication_token(token)),
                AccountLoggedIn(account.id, is_new_account=True),
            ],
        )
        return account, session, raw_session_token

    async def login(
        self,
        email: Email,
        password: str,
        client_ip: str,
        *,
        now: datetime | None = None,
    ) -> tuple[Account, Session, str]:
        now = now or datetime.now(UTC)
        await self._throttle.check(email, client_ip)
        account = await self._repository.get_account_by_email(email)
        account_is_active = account is not None and account.deactivated_at is None
        stored_hash = account.password_hash if account_is_active and account else DUMMY_PASSWORD_HASH
        verified = await run_in_threadpool(password_hash.verify, password, stored_hash)
        if not account_is_active or not verified:
            await self._throttle.failed(email, client_ip)
            raise AuthenticationError
        assert account is not None

        await self._throttle.succeeded(email, client_ip)
        session, raw_session_token = self._new_session(account.id, now)
        await self._repository.save(session, events=[AccountLoggedIn(account.id, is_new_account=False)])
        return account, session, raw_session_token

    async def authenticate_session(self, token: str, *, now: datetime | None = None) -> tuple[Session, Account] | None:
        now = now or datetime.now(UTC)
        return await self._repository.get_authenticated_session(_token_hash(token), now)

    async def logout(self, session: Session, *, now: datetime | None = None) -> None:
        session.revoked_at = now or datetime.now(UTC)
        await self._repository.save()

    async def verify_email(self, token: str, *, now: datetime | None = None) -> Account:
        return await self._consume_credential(token, CredentialPurpose.EMAIL_VERIFICATION, now=now)

    async def request_verification(self, email: Email, *, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        account = await self._repository.get_account_by_email(email)
        if account is None or account.email_verified_at is not None or account.deactivated_at is not None:
            return

        await self._revoke_credentials(account.id, CredentialPurpose.EMAIL_VERIFICATION, now=now)
        token = _new_token()
        credential = AccountCredential(
            account_id=account.id,
            purpose=CredentialPurpose.EMAIL_VERIFICATION.value,
            token_hash=_token_hash(token),
            expires_at=now + VERIFICATION_LIFETIME,
        )
        await self._repository.save(
            credential,
            events=[AccountVerificationRequested(account.email, encrypt_authentication_token(token))],
        )

    async def request_password_reset(self, email: Email, *, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        account = await self._repository.get_account_by_email(email)
        if account is None or account.deactivated_at is not None:
            return
        await self._revoke_credentials(account.id, CredentialPurpose.PASSWORD_RESET, now=now)
        token = _new_token()
        credential = AccountCredential(
            account_id=account.id,
            purpose=CredentialPurpose.PASSWORD_RESET.value,
            token_hash=_token_hash(token),
            expires_at=now + PASSWORD_RESET_LIFETIME,
        )
        await self._repository.save(
            credential,
            events=[PasswordResetRequested(account.email, encrypt_authentication_token(token))],
        )

    async def reset_password(self, token: str, new_password: str, *, now: datetime | None = None) -> Account:
        Password(new_password)
        account = await self._consume_credential(token, CredentialPurpose.PASSWORD_RESET, now=now, commit=False)
        account.password_hash = await run_in_threadpool(password_hash.hash, new_password)
        await self._revoke_sessions(account.id, now=now)
        await self._repository.save()
        return account

    async def change_password(
        self, account: Account, current_password: str, new_password: str, *, now: datetime | None = None
    ) -> None:
        Password(new_password)
        if not await run_in_threadpool(password_hash.verify, current_password, account.password_hash):
            raise AuthenticationError
        account.password_hash = await run_in_threadpool(password_hash.hash, new_password)
        await self._revoke_sessions(account.id, now=now)
        await self._repository.save()

    async def _consume_credential(
        self,
        token: str,
        purpose: CredentialPurpose,
        *,
        now: datetime | None = None,
        commit: bool = True,
    ) -> Account:
        now = now or datetime.now(UTC)
        credential = await self._repository.get_credential_for_update(_token_hash(token), purpose, now)
        if credential is None:
            raise InvalidCredentialToken
        account = await self._repository.get_account(credential.account_id)
        if account is None or account.deactivated_at is not None:
            raise InvalidCredentialToken
        credential.consumed_at = now
        if purpose is CredentialPurpose.EMAIL_VERIFICATION:
            account.email_verified_at = now
        if commit:
            await self._repository.save()
        return account

    async def _revoke_credentials(
        self,
        account_id: uuid.UUID,
        purpose: CredentialPurpose,
        *,
        now: datetime,
    ) -> None:
        credentials = await self._repository.get_unconsumed_credentials(account_id, purpose)
        for credential in credentials:
            credential.consumed_at = now

    async def _revoke_sessions(self, account_id: uuid.UUID, *, now: datetime | None = None) -> None:
        revoked_at = now or datetime.now(UTC)
        sessions = await self._repository.get_active_sessions(account_id)
        for session in sessions:
            session.revoked_at = revoked_at

    @staticmethod
    def _new_session(account_id: uuid.UUID, now: datetime) -> tuple[Session, str]:
        token = _new_token()
        return (
            Session(account_id=account_id, token_hash=_token_hash(token), expires_at=now + SESSION_LIFETIME),
            token,
        )


def csrf_token(session_token: str, secret: str) -> str:
    return hmac.new(secret.encode(), f"eventhub-csrf:{session_token}".encode(), hashlib.sha256).hexdigest()


def verify_csrf_token(session_token: str, secret: str, supplied: str | None) -> bool:
    if not supplied:
        return False
    return hmac.compare_digest(csrf_token(session_token, secret), supplied)
