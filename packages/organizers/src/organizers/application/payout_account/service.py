from typing import Annotated

from libs.time_utils import Clock, utc_now
from shared.domain.errors import InvalidStateTransition
from shared.infra.di import Depends

from organizers.domain.models.organization.errors import OrganizationAccessDenied, OrganizationNotFound
from organizers.domain.models.organization.organization import Organization
from organizers.domain.models.organization.repository import OrganizationRepository, OrganizationRepositoryDep
from organizers.domain.models.organization.values import AccountID, OrganizationID
from organizers.domain.models.payout_account.errors import PayoutAccountNotFound
from organizers.domain.models.payout_account.payout_account import PayoutAccount
from organizers.domain.models.payout_account.repository import PayoutAccountRepository, PayoutAccountRepositoryDep
from organizers.domain.models.payout_account.values import BankPayoutDetails, PayoutAccountID, PixPayoutDetails


class PayoutAccountService:
    def __init__(
        self,
        organization_repository: OrganizationRepository,
        payout_account_repository: PayoutAccountRepository,
        clock: Clock = utc_now,
    ) -> None:
        self._organizations = organization_repository
        self._payout_accounts = payout_account_repository
        self._clock = clock

    async def submit(
        self,
        organization_id: OrganizationID,
        account_id: AccountID,
        *,
        details: PixPayoutDetails | BankPayoutDetails,
    ) -> PayoutAccount:
        organization = await self._get_owner_organization(organization_id, account_id)
        self._ensure_no_pending_payout_account(organization)
        if isinstance(details, PixPayoutDetails):
            payout_account = PayoutAccount.create_pix(
                organization_id=organization.id,
                organization_type=organization.organization_type,
                details=details,
                now=self._clock(),
            )
        else:
            payout_account = PayoutAccount.create_bank_transfer(
                organization_id=organization.id,
                organization_type=organization.organization_type,
                details=details,
                now=self._clock(),
            )
        organization.pending_payout_account_id = payout_account.id
        organization.updated_at = self._clock()
        await self._payout_accounts.save(organization, payout_account)
        return payout_account

    async def approve(self, organization_id: OrganizationID, payout_account_id: PayoutAccountID) -> PayoutAccount:
        organization = await self._get_organization(organization_id)
        payout_account = await self._get_payout_account(payout_account_id)
        if organization.pending_payout_account_id != payout_account.id:
            raise InvalidStateTransition("This payout account is not pending for the organization")
        now = self._clock()
        old_account = (
            await self._get_payout_account(organization.current_payout_account_id)
            if organization.current_payout_account_id
            else None
        )
        if old_account is not None:
            old_account.supersede(now=now)
        payout_account.verify(now=now)
        organization.current_payout_account_id = payout_account.id
        organization.pending_payout_account_id = None
        organization.updated_at = now
        await self._payout_accounts.save(organization, payout_account, *([old_account] if old_account else []))
        return payout_account

    async def reject(
        self, organization_id: OrganizationID, payout_account_id: PayoutAccountID, reason: str
    ) -> PayoutAccount:
        organization = await self._get_organization(organization_id)
        payout_account = await self._get_payout_account(payout_account_id)
        if organization.pending_payout_account_id != payout_account.id:
            raise InvalidStateTransition("This payout account is not pending for the organization")
        now = self._clock()
        payout_account.reject(reason, now=now)
        organization.pending_payout_account_id = None
        organization.updated_at = now
        await self._payout_accounts.save(organization, payout_account)
        return payout_account

    async def list_pending_review(self) -> list[PayoutAccount]:
        """Internal review queue; not exposed through the public HTTP API."""
        return await self._payout_accounts.list_pending_review()

    async def get_for_organization(
        self, organization_id: OrganizationID, account_id: AccountID
    ) -> tuple[PayoutAccount | None, PayoutAccount | None]:
        organization = await self._get_owner_organization(organization_id, account_id)
        current = (
            await self._get_payout_account(organization.current_payout_account_id)
            if organization.current_payout_account_id
            else None
        )
        pending = (
            await self._get_payout_account(organization.pending_payout_account_id)
            if organization.pending_payout_account_id
            else None
        )
        return current, pending

    async def _get_owner_organization(self, organization_id: OrganizationID, account_id: AccountID) -> Organization:
        organization = await self._organizations.get_for_member(organization_id, account_id)
        if organization is None:
            raise OrganizationNotFound

        if not organization.has_owner(account_id):
            raise OrganizationAccessDenied

        return organization

    async def _get_organization(self, organization_id: OrganizationID) -> Organization:
        organization = await self._organizations.get(organization_id)
        if organization is None:
            raise OrganizationNotFound

        return organization

    async def _get_payout_account(self, payout_account_id: PayoutAccountID | None) -> PayoutAccount:
        if payout_account_id is None:
            raise PayoutAccountNotFound

        payout_account = await self._payout_accounts.get(payout_account_id)
        if payout_account is None:
            raise PayoutAccountNotFound

        return payout_account

    @staticmethod
    def _ensure_no_pending_payout_account(organization: Organization) -> None:
        if organization.pending_payout_account_id is not None:
            raise InvalidStateTransition("A payout account is already waiting for review")


async def __get_service(
    organization_repository: OrganizationRepositoryDep,
    payout_account_repository: PayoutAccountRepositoryDep,
) -> PayoutAccountService:
    return PayoutAccountService(organization_repository, payout_account_repository)


PayoutAccountServiceDep = Annotated[PayoutAccountService, Depends(__get_service)]
