from typing import Annotated

from libs.events import PublishableEvent
from shared.domain.errors import ConcurrencyConflict
from shared.infra.database import SessionDep
from shared.infra.di import Depends
from shared.infra.outbox import add_to_outbox
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import StaleDataError
from sqlmodel import col, select

from organizers.domain.models.organization.organization import Member, Organization, PayoutAccount
from organizers.domain.models.organization.values import (
    AccountID,
    OrganizationID,
    PayoutAccountID,
    PayoutAccountStatus,
    VerificationStatus,
)


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, organization_id: OrganizationID) -> Organization | None:
        query = (
            select(Organization)
            .where(col(Organization.id) == organization_id)
            .options(selectinload(Organization.members))  # ty:ignore[invalid-argument-type]
        )
        result = await self._session.execute(query)
        return result.scalars().first()

    async def get_for_member(self, organization_id: OrganizationID, account_id: AccountID) -> Organization | None:
        query = (
            select(Organization)
            .join(Member, col(Organization.id) == col(Member.organization_id))
            .where(col(Organization.id) == organization_id, col(Member.account_id) == account_id)
            .options(selectinload(Organization.members))  # ty:ignore[invalid-argument-type]
        )
        result = await self._session.execute(query)
        return result.scalars().first()

    async def list_for_account(self, account_id: AccountID) -> list[Organization]:
        query = (
            select(Organization)
            .join(Member, col(Organization.id) == col(Member.organization_id))
            .where(col(Member.account_id) == account_id)
            .options(selectinload(Organization.members))  # ty:ignore[invalid-argument-type]
            .order_by(col(Organization.created_at), col(Organization.id))
        )
        result = await self._session.execute(query)
        return list(result.scalars().unique().all())

    async def list_pending_verification(self) -> list[Organization]:
        query = (
            select(Organization)
            .where(col(Organization.verification_status) == VerificationStatus.PENDING)
            .options(selectinload(Organization.members))  # ty:ignore[invalid-argument-type]
            .order_by(col(Organization.created_at), col(Organization.id))
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_payout_account(self, payout_account_id: PayoutAccountID) -> PayoutAccount | None:
        return await self._session.get(PayoutAccount, payout_account_id)

    async def list_pending_payout_accounts(self) -> list[PayoutAccount]:
        query = (
            select(PayoutAccount)
            .where(col(PayoutAccount.status) == PayoutAccountStatus.PENDING)
            .order_by(col(PayoutAccount.created_at), col(PayoutAccount.id))
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def save(self, organization: Organization, *payout_accounts: PayoutAccount) -> None:
        organization_id = organization.id
        self._session.add(organization)
        self._session.add_all(payout_accounts)

        pending_events: list[PublishableEvent] = organization.pull_events()
        for payout_account in payout_accounts:
            pending_events.extend(payout_account.pull_events())
        add_to_outbox(self._session, pending_events)

        try:
            await self._session.commit()
        except StaleDataError as exc:
            await self._session.rollback()
            raise ConcurrencyConflict(f"Organization {organization_id} was modified by someone else") from exc


async def __get_repository(session: SessionDep) -> OrganizationRepository:
    return OrganizationRepository(session)


OrganizationRepositoryDep = Annotated[OrganizationRepository, Depends(__get_repository)]
