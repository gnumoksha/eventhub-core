from typing import Annotated

from libs.time_utils import Clock, utc_now
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
    OrganizationLegalProfile,
)


class OrganizationService:
    def __init__(self, repository: OrganizationRepository, clock: Clock = utc_now) -> None:
        self._repository = repository
        self._clock = clock

    async def create(
        self,
        *,
        owner_account_id: AccountID,
        public_name: str,
    ) -> Organization:
        organization = Organization.create(
            public_name=public_name,
            owner_account_id=owner_account_id,
            now=self._clock(),
        )
        await self._repository.save(organization)
        return organization

    async def list_for_account(self, account_id: AccountID) -> list[Organization]:
        return await self._repository.list_for_account(account_id)

    async def list_paginated_for_account(
        self, account_id: AccountID, *, limit: int = 10, offset: int = 0
    ) -> tuple[list[Organization], int]:
        return await self._repository.list_paginated_for_account(account_id, limit=limit, offset=offset)

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
        legal_profile: OrganizationLegalProfile | None = None,
    ) -> Organization:
        organization = await self._get_owner_organization(organization_id, account_id)
        if legal_profile is not None:
            organization.update_legal_profile(legal_profile, now=self._clock())
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


async def __get_service(repository: OrganizationRepositoryDep) -> OrganizationService:
    return OrganizationService(repository)


OrganizationServiceDep = Annotated[OrganizationService, Depends(__get_service)]
