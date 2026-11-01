from typing import Annotated

from libs.time_utils import Clock, utc_now
from shared.domain.errors import InvalidStateTransition
from shared.infra.di import Depends

from organizers.domain.models.organization.errors import (
    OrganizationAccessDenied,
    OrganizationNotFound,
)
from organizers.domain.models.organization.organization import Organization
from organizers.domain.models.organization.repository import OrganizationRepository, OrganizationRepositoryDep
from organizers.domain.models.organization.values import (
    AccountID,
    MemberRole,
    OrganizationID,
    OrganizationProfile,
    OrganizationType,
    TaxIdentifier,
)
from organizers.domain.models.payout_account.errors import PayoutAccountNotFound
from organizers.domain.models.payout_account.payout_account import PayoutAccount
from organizers.domain.models.payout_account.values import BankPayoutDetails, PayoutAccountID, PixPayoutDetails


class OrganizationService:
    def __init__(self, repository: OrganizationRepository, clock: Clock = utc_now) -> None:
        self._repository = repository
        self._clock = clock

    async def create(
        self,
        *,
        owner_account_id: AccountID,
        organization_type: OrganizationType,
        public_name: str,
        legal_name: str,
        tax_id: str,
    ) -> Organization:
        tax_id = TaxIdentifier(tax_id, organization_type).value
        organization = Organization.create(
            profile=OrganizationProfile(organization_type, public_name, legal_name, tax_id),
            owner_account_id=owner_account_id,
            now=self._clock(),
        )
        await self._repository.save(organization)
        return organization

    async def list_for_account(self, account_id: AccountID) -> list[Organization]:
        return await self._repository.list_for_account(account_id)

    async def get(self, organization_id: OrganizationID, account_id: AccountID) -> Organization:
        organization = await self._repository.get_for_member(organization_id, account_id)
        if organization is None:
            raise OrganizationNotFound
        return organization

    async def update_public_name(
        self, organization_id: OrganizationID, account_id: AccountID, public_name: str
    ) -> Organization:
        organization = await self._get_owner_organization(organization_id, account_id)
        organization.update_public_name(public_name, now=self._clock())
        await self._repository.save(organization)
        return organization

    async def update_profile(
        self,
        organization_id: OrganizationID,
        account_id: AccountID,
        *,
        public_name: str | None = None,
        legal_name: str | None = None,
        tax_id: str | None = None,
    ) -> Organization:
        organization = await self._get_owner_organization(organization_id, account_id)
        if legal_name is not None or tax_id is not None:
            if legal_name is None or tax_id is None:
                raise InvalidStateTransition("Legal name and tax ID must be updated together")
            organization.update_legal_profile(legal_name, tax_id, now=self._clock())
        if public_name is not None:
            organization.update_public_name(public_name, now=self._clock())
        await self._repository.save(organization)
        return organization

    async def add_member(
        self,
        organization_id: OrganizationID,
        account_id: AccountID,
        new_account_id: AccountID,
        role: MemberRole,
    ) -> Organization:
        organization = await self._get_owner_organization(organization_id, account_id)
        organization.add_member(new_account_id, role, now=self._clock())
        await self._repository.save(organization)
        return organization

    async def remove_member(
        self, organization_id: OrganizationID, account_id: AccountID, member_account_id: AccountID
    ) -> Organization:
        organization = await self._get_owner_organization(organization_id, account_id)
        organization.remove_member(member_account_id, now=self._clock())
        await self._repository.save(organization)
        return organization

    async def submit_verification(self, organization_id: OrganizationID, account_id: AccountID) -> Organization:
        organization = await self._get_owner_organization(organization_id, account_id)
        organization.submit_verification(now=self._clock())
        await self._repository.save(organization)
        return organization

    async def approve_organization(self, organization_id: OrganizationID) -> Organization:
        organization = await self._get_organization(organization_id)
        organization.verify(now=self._clock())
        await self._repository.save(organization)
        return organization

    async def list_organizations_pending_review(self) -> list[Organization]:
        """Internal review queue; not exposed through the public HTTP API."""
        return await self._repository.list_pending_verification()

    async def reject_organization(self, organization_id: OrganizationID, reason: str) -> Organization:
        organization = await self._get_organization(organization_id)
        organization.reject_verification(reason, now=self._clock())
        await self._repository.save(organization)
        return organization

    async def submit_payout_account(
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
        await self._repository.save(organization, payout_account)
        return payout_account

    async def approve_payout_account(
        self, organization_id: OrganizationID, payout_account_id: PayoutAccountID
    ) -> PayoutAccount:
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
        await self._repository.save(organization, payout_account, *([old_account] if old_account else []))
        return payout_account

    async def reject_payout_account(
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
        await self._repository.save(organization, payout_account)
        return payout_account

    async def list_payout_accounts_pending_review(self) -> list[PayoutAccount]:
        """Internal review queue; not exposed through the public HTTP API."""
        return await self._repository.list_pending_payout_accounts()

    async def get_payout_accounts(
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
        organization = await self.get(organization_id, account_id)
        if not organization.has_owner(account_id):
            raise OrganizationAccessDenied
        return organization

    async def _get_organization(self, organization_id: OrganizationID) -> Organization:
        organization = await self._repository.get(organization_id)
        if organization is None:
            raise OrganizationNotFound
        return organization

    async def _get_payout_account(self, payout_account_id: PayoutAccountID | None) -> PayoutAccount:
        if payout_account_id is None:
            raise PayoutAccountNotFound
        payout_account = await self._repository.get_payout_account(payout_account_id)
        if payout_account is None:
            raise PayoutAccountNotFound
        return payout_account

    @staticmethod
    def _ensure_no_pending_payout_account(organization: Organization) -> None:
        if organization.pending_payout_account_id is not None:
            raise InvalidStateTransition("A payout account is already waiting for review")


async def __get_service(repository: OrganizationRepositoryDep) -> OrganizationService:
    return OrganizationService(repository)


OrganizationServiceDep = Annotated[OrganizationService, Depends(__get_service)]
