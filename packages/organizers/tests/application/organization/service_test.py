import uuid

import pytest
from organizers.application.listeners import remove_deactivated_memberships
from organizers.application.organization.service import OrganizationService
from organizers.domain.models.organization.errors import OrganizationAccessDenied
from organizers.domain.models.organization.values import MemberRole, OrganizationLegalProfile, TaxIDType
from shared.domain.errors import InvalidValue

from tests.conftest import InMemoryOrganizationRepository


@pytest.mark.asyncio
async def test_non_owner_cannot_manage_members(
    service: OrganizationService,
    create_organization_with_legal_profile,
    repository: InMemoryOrganizationRepository,
):
    organization = await create_organization_with_legal_profile()
    staff_account_id = uuid.uuid4()
    organization.add_member(staff_account_id, MemberRole.STAFF, now=organization.updated_at)

    with pytest.raises(OrganizationAccessDenied):
        await service.add_member(organization.id, staff_account_id, uuid.uuid4(), MemberRole.STAFF)


@pytest.mark.asyncio
async def test_deactivated_non_owner_membership_is_removed(service, create_organization_with_legal_profile, repository):
    organization = await create_organization_with_legal_profile()
    staff_account_id = uuid.uuid4()
    organization.add_member(staff_account_id, MemberRole.STAFF, now=organization.updated_at)
    await repository.save(organization)

    await remove_deactivated_memberships(staff_account_id, repository)
    assert await service.list_for_account(staff_account_id) == []


@pytest.mark.asyncio
async def test_deactivated_owner_membership_is_preserved(
    service, create_organization_with_legal_profile, repository, account_id
):
    organization = await create_organization_with_legal_profile()

    await remove_deactivated_memberships(account_id, repository)

    assert organization.has_owner(account_id)


@pytest.mark.asyncio
async def test_tax_id_validation_uses_tax_id_type(service, account_id):
    organization = await service.create(owner_account_id=account_id, public_name="Bad ID")

    with pytest.raises(InvalidValue):
        await service.update_profile(
            organization.id,
            account_id,
            legal_profile=OrganizationLegalProfile("Invalid", "not-a-cpf", TaxIDType.CPF),
        )


@pytest.mark.asyncio
async def test_internal_review_queue_lists_only_pending_organizations(
    service, create_organization_with_legal_profile, account_id
):
    organization = await create_organization_with_legal_profile()
    await service.submit_verification(organization.id, account_id)
    assert await service.list_organizations_pending_review() == [organization]

    await service.approve_organization(organization.id)
    assert await service.list_organizations_pending_review() == []
