import uuid

import pytest
from organizers.application.payout_account.service import PayoutAccountService
from organizers.domain.models.payout_account.events import PayoutAccountVerified
from organizers.domain.models.payout_account.values import BankPayoutDetails, PayoutAccountStatus, PixPayoutDetails
from shared.domain.values.financial import Pix, PixKeyType

from tests.conftest import InMemoryPayoutAccountRepository


@pytest.mark.asyncio
async def test_replacement_keeps_current_account_until_new_account_is_approved(
    payout_account_service: PayoutAccountService,
    create_organization_with_legal_profile,
    payout_repository: InMemoryPayoutAccountRepository,
    account_id: uuid.UUID,
):
    organization = await create_organization_with_legal_profile()
    first = await payout_account_service.submit(
        organization.id,
        account_id,
        details=PixPayoutDetails(Pix("first@example.com", PixKeyType.EMAIL), "Maria da Silva", "52998224725"),
    )
    await payout_account_service.approve(organization.id, first.id)
    second = await payout_account_service.submit(
        organization.id,
        account_id,
        details=BankPayoutDetails("001", "1234", "123456", "7", "checking", "Maria da Silva", "52998224725"),
    )

    assert organization.current_payout_account_id == first.id
    assert organization.pending_payout_account_id == second.id
    assert payout_repository.payout_accounts[first.id].status == PayoutAccountStatus.VERIFIED
    assert not organization.can_sell_paid_tickets

    await payout_account_service.approve(organization.id, second.id)

    assert organization.current_payout_account_id == second.id
    assert organization.pending_payout_account_id is None
    assert payout_repository.payout_accounts[first.id].status == PayoutAccountStatus.SUPERSEDED
    assert payout_repository.payout_accounts[second.id].status == PayoutAccountStatus.VERIFIED
    assert isinstance(payout_repository.outbox[-1], PayoutAccountVerified)


@pytest.mark.asyncio
async def test_internal_review_queue_lists_only_pending_payout_accounts(
    payout_account_service: PayoutAccountService,
    create_organization_with_legal_profile,
    account_id: uuid.UUID,
):
    organization = await create_organization_with_legal_profile()
    payout_account = await payout_account_service.submit(
        organization.id,
        account_id,
        details=PixPayoutDetails(Pix("first@example.com", PixKeyType.EMAIL), "Maria da Silva", "52998224725"),
    )

    assert await payout_account_service.list_pending_review() == [payout_account]

    await payout_account_service.approve(organization.id, payout_account.id)

    assert await payout_account_service.list_pending_review() == []
