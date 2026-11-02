import uuid

from organizers.domain.models.organization.values import (
    OrganizationType,
)
from organizers.domain.models.payout_account.payout_account import PayoutAccount
from organizers.domain.models.payout_account.values import PayoutAccountStatus, PixPayoutDetails
from shared.domain.values.financial import Pix, PixKeyType

from tests.conftest import NOW


def test_pix_account_is_pending_until_verified():
    payout = PayoutAccount.create_pix(
        organization_id=uuid.uuid4(),
        organization_type=OrganizationType.INDIVIDUAL,
        details=PixPayoutDetails(Pix("maria@example.com", PixKeyType.EMAIL), "Maria da Silva", "52998224725"),
        now=NOW,
    )

    assert payout.status == PayoutAccountStatus.PENDING
    payout.verify(now=NOW)
    assert payout.status == PayoutAccountStatus.VERIFIED
