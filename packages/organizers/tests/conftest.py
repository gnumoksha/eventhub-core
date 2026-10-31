import uuid
from datetime import UTC, datetime
from typing import override

import pytest
from libs.events import PublishableEvent
from libs.time_utils import FakeClock
from organizers.application.organization.service import OrganizationService
from organizers.domain.models.organization.organization import Organization, PayoutAccount
from organizers.domain.models.organization.repository import OrganizationRepository
from organizers.domain.models.organization.values import (
    OrganizationID,
    OrganizationType,
    PayoutAccountID,
    PayoutAccountStatus,
    VerificationStatus,
)

NOW = datetime(2030, 1, 10, 12, 0, tzinfo=UTC)


class InMemoryOrganizationRepository(OrganizationRepository):
    def __init__(self) -> None:
        self.organizations: dict[OrganizationID, Organization] = {}
        self.payout_accounts: dict[PayoutAccountID, PayoutAccount] = {}
        self.outbox: list[PublishableEvent] = []

    @override
    async def get(self, organization_id: OrganizationID) -> Organization | None:
        return self.organizations.get(organization_id)

    @override
    async def get_for_member(self, organization_id: OrganizationID, account_id: uuid.UUID) -> Organization | None:
        org = self.organizations.get(organization_id)
        return org if org and org.has_member(account_id) else None

    @override
    async def list_for_account(self, account_id: uuid.UUID) -> list[Organization]:
        return [org for org in self.organizations.values() if org.has_member(account_id)]

    @override
    async def list_pending_verification(self) -> list[Organization]:
        return [org for org in self.organizations.values() if org.verification_status == VerificationStatus.PENDING]

    @override
    async def get_payout_account(self, payout_account_id: PayoutAccountID) -> PayoutAccount | None:
        return self.payout_accounts.get(payout_account_id)

    @override
    async def list_pending_payout_accounts(self) -> list[PayoutAccount]:
        return [payout for payout in self.payout_accounts.values() if payout.status == PayoutAccountStatus.PENDING]

    @override
    async def save(self, organization: Organization, *payout_accounts: PayoutAccount) -> None:
        organization.version += 1
        self.organizations[organization.id] = organization
        self.outbox.extend(organization.pull_events())
        for payout_account in payout_accounts:
            payout_account.version += 1
            self.payout_accounts[payout_account.id] = payout_account
            self.outbox.extend(payout_account.pull_events())


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def account_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def repository() -> InMemoryOrganizationRepository:
    return InMemoryOrganizationRepository()


@pytest.fixture
def clock(now: datetime) -> FakeClock:
    return FakeClock(now)


@pytest.fixture
def service(repository: InMemoryOrganizationRepository, clock: FakeClock) -> OrganizationService:
    return OrganizationService(repository, clock)


@pytest.fixture
def create_individual(service: OrganizationService, account_id: uuid.UUID):
    async def create() -> Organization:
        return await service.create(
            owner_account_id=account_id,
            organization_type=OrganizationType.INDIVIDUAL,
            public_name="Event Crew",
            legal_name="Maria da Silva",
            tax_id="529.982.247-25",
        )

    return create
