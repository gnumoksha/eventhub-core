from typing import Annotated

from libs.events import PublishableEvent
from shared.domain.errors import ConcurrencyConflict
from shared.infra.database import SessionDep
from shared.infra.di import Depends
from shared.infra.outbox import add_to_outbox
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError
from sqlmodel import col, select

from organizers.domain.models.organization.organization import Organization
from organizers.domain.models.organization.values import OrganizationID
from organizers.domain.models.payout_account.payout_account import PayoutAccount
from organizers.domain.models.payout_account.values import PayoutAccountID, PayoutAccountStatus


class PayoutAccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, payout_account_id: PayoutAccountID) -> PayoutAccount | None:
        return await self._session.get(PayoutAccount, payout_account_id)

    async def list_pending_review(self) -> list[PayoutAccount]:
        query = (
            select(PayoutAccount)
            .where(col(PayoutAccount.status) == PayoutAccountStatus.PENDING)
            .order_by(col(PayoutAccount.created_at), col(PayoutAccount.id))
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def save(self, organization: Organization, *payout_accounts: PayoutAccount) -> None:
        organization_id: OrganizationID = organization.id
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


async def __get_repository(session: SessionDep) -> PayoutAccountRepository:
    return PayoutAccountRepository(session)


PayoutAccountRepositoryDep = Annotated[PayoutAccountRepository, Depends(__get_repository)]
