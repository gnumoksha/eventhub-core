import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Annotated

from libs.events import PublishableEvent
from shared.infra.database import SessionDep
from shared.infra.di import Depends
from shared.infra.outbox import add_to_outbox
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from identity.domain.models.account.account import Account, AccountCredential, CredentialPurpose, Session
from identity.domain.models.values import Email


class AccountEmailAlreadyExists(Exception):
    """An account already uses the requested e-mail address."""


def _get_constraint_name(error: BaseException | None) -> str | None:
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        constraint_name = getattr(current, "constraint_name", None) or getattr(
            getattr(current, "diag", None), "constraint_name", None
        )
        if constraint_name is not None:
            return constraint_name
        current = current.__cause__ or current.__context__
    return None


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_account_by_email(self, email: Email) -> Account | None:
        result = await self._session.execute(select(Account).where(col(Account.email) == email.value))
        return result.scalars().first()

    async def get_account(self, account_id: uuid.UUID) -> Account | None:
        return await self._session.get(Account, account_id)

    async def get_authenticated_session(self, token_hash: str, now: datetime) -> tuple[Session, Account] | None:
        query = (
            select(Session, Account)
            .join(Account, col(Account.id) == col(Session.account_id))
            .where(
                col(Session.token_hash) == token_hash,
                col(Session.revoked_at).is_(None),
                col(Session.expires_at) > now,
                col(Account.deactivated_at).is_(None),
            )
        )
        result = await self._session.execute(query)
        row = result.first()
        return (row[0], row[1]) if row else None

    async def get_credential_for_update(
        self,
        token_hash: str,
        purpose: CredentialPurpose,
        now: datetime,
    ) -> AccountCredential | None:
        query = (
            select(AccountCredential)
            .where(
                col(AccountCredential.token_hash) == token_hash,
                col(AccountCredential.purpose) == purpose.value,
                col(AccountCredential.consumed_at).is_(None),
                col(AccountCredential.expires_at) > now,
            )
            .with_for_update()
        )
        result = await self._session.execute(query)
        return result.scalars().first()

    async def get_unconsumed_credentials(
        self, account_id: uuid.UUID, purpose: CredentialPurpose
    ) -> list[AccountCredential]:
        query = select(AccountCredential).where(
            col(AccountCredential.account_id) == account_id,
            col(AccountCredential.purpose) == purpose.value,
            col(AccountCredential.consumed_at).is_(None),
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_active_sessions(self, account_id: uuid.UUID) -> list[Session]:
        query = select(Session).where(
            col(Session.account_id) == account_id,
            col(Session.revoked_at).is_(None),
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    def add(self, *entities: Account | AccountCredential | Session) -> None:
        self._session.add_all(entities)

    async def flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            if _get_constraint_name(exc.orig) == "uq_identity_accounts_email":
                raise AccountEmailAlreadyExists from exc
            raise

    async def save(
        self,
        *entities: Account | AccountCredential | Session,
        events: Iterable[PublishableEvent] = (),
    ) -> None:
        self._session.add_all(entities)
        add_to_outbox(self._session, events)
        await self._session.commit()


async def __get_repository(session: SessionDep) -> AccountRepository:
    return AccountRepository(session)


AccountRepositoryDep = Annotated[AccountRepository, Depends(__get_repository)]
