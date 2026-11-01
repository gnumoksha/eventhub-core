import uuid

import pytest
from organizers.application.listeners import remove_deactivated_memberships
from organizers.application.organization.service import OrganizationService
from organizers.domain.models.organization.errors import OrganizationAccessDenied
from organizers.domain.models.organization.values import (
    MemberRole,
    OrganizationType,
)
from organizers.domain.models.payout_account.events import PayoutAccountVerified
from organizers.domain.models.payout_account.values import BankPayoutDetails, PayoutAccountStatus, PixPayoutDetails
from shared.domain.errors import InvalidValue
from shared.domain.values.financial import Pix, PixKeyType

from tests.conftest import InMemoryOrganizationRepository


@pytest.mark.asyncio
async def test_non_owner_cannot_manage_members(
    service: OrganizationService,
    create_individual,
    repository: InMemoryOrganizationRepository,
):
    organization = await create_individual()
    staff_account_id = uuid.uuid4()
    organization.add_member(staff_account_id, MemberRole.STAFF, now=organization.updated_at)

    with pytest.raises(OrganizationAccessDenied):
        await service.add_member(organization.id, staff_account_id, uuid.uuid4(), MemberRole.STAFF)


@pytest.mark.asyncio
async def test_payout_account_replacement_keeps_current_until_approval(
    service: OrganizationService,
    create_individual,
    repository: InMemoryOrganizationRepository,
    account_id: uuid.UUID,
):
    organization = await create_individual()
    first = await service.submit_payout_account(
        organization.id,
        account_id,
        details=PixPayoutDetails(Pix("first@example.com", PixKeyType.EMAIL), "Maria da Silva", "52998224725"),
    )
    await service.approve_payout_account(organization.id, first.id)
    second = await service.submit_payout_account(
        organization.id,
        account_id,
        details=BankPayoutDetails("001", "1234", "123456", "7", "checking", "Maria da Silva", "52998224725"),
    )

    assert organization.current_payout_account_id == first.id
    assert organization.pending_payout_account_id == second.id
    assert repository.payout_accounts[first.id].status == PayoutAccountStatus.VERIFIED
    assert not organization.can_sell_paid_tickets

    await service.approve_payout_account(organization.id, second.id)

    assert organization.current_payout_account_id == second.id
    assert organization.pending_payout_account_id is None
    assert repository.payout_accounts[first.id].status == PayoutAccountStatus.SUPERSEDED
    assert repository.payout_accounts[second.id].status == PayoutAccountStatus.VERIFIED
    assert isinstance(repository.outbox[-1], PayoutAccountVerified)

    await service.submit_verification(organization.id, account_id)
    await service.approve_organization(organization.id)
    assert organization.can_sell_paid_tickets


@pytest.mark.asyncio
async def test_deactivated_non_owner_membership_is_removed(service, create_individual, repository):
    organization = await create_individual()
    staff_account_id = uuid.uuid4()
    organization.add_member(staff_account_id, MemberRole.STAFF, now=organization.updated_at)
    await repository.save(organization)

    await remove_deactivated_memberships(staff_account_id, repository)
    assert await service.list_for_account(staff_account_id) == []


@pytest.mark.asyncio
async def test_deactivated_owner_membership_is_preserved(service, create_individual, repository, account_id):
    organization = await create_individual()

    await remove_deactivated_memberships(account_id, repository)

    assert organization.has_owner(account_id)


@pytest.mark.asyncio
async def test_person_type_validates_tax_id_during_creation(service, account_id):
    with pytest.raises(InvalidValue):
        await service.create(
            owner_account_id=account_id,
            organization_type=OrganizationType.INDIVIDUAL,
            public_name="Bad ID",
            legal_name="Invalid",
            tax_id="not-a-cpf",
        )


@pytest.mark.asyncio
async def test_internal_review_queues_only_pending_items(service, create_individual, account_id):
    organization = await create_individual()
    await service.submit_verification(organization.id, account_id)
    assert await service.list_organizations_pending_review() == [organization]

    await service.approve_organization(organization.id)
    assert await service.list_organizations_pending_review() == []

    payout = await service.submit_payout_account(
        organization.id,
        account_id,
        details=PixPayoutDetails(Pix("first@example.com", PixKeyType.EMAIL), "Maria da Silva", "52998224725"),
    )
    assert await service.list_payout_accounts_pending_review() == [payout]

    await service.approve_payout_account(organization.id, payout.id)
    assert await service.list_payout_accounts_pending_review() == []
