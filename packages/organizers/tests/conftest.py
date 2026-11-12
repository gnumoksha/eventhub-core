import uuid
from datetime import UTC, datetime
from typing import override

import pytest
from libs.events import PublishableEvent
from libs.time_utils import FakeClock
from organizers.application.organization.service import OrganizationService
from organizers.application.payout_account.service import PayoutAccountService
from organizers.domain.models.organization.organization import Organization
from organizers.domain.models.organization.repository import OrganizationRepository
from organizers.domain.models.organization.values import (
    OrganizationID,
    OrganizationLegalProfile,
    TaxIDType,
    VerificationStatus,
)
from organizers.domain.models.payout_account.payout_account import PayoutAccount
from organizers.domain.models.payout_account.repository import PayoutAccountRepository
from organizers.domain.models.payout_account.values import PayoutAccountID, PayoutAccountStatus

NOW = datetime(2030, 1, 10, 12, 0, tzinfo=UTC)


class InMemoryOrganizationRepository(OrganizationRepository):
    def __init__(self) -> None:
        self.organizations: dict[OrganizationID, Organization] = {}
        self.outbox: list[PublishableEvent] = []

    @override
    async def get(self, organization_id: OrganizationID) -> Organization | None:
        return self.organizations.get(organization_id)

    @override
    async def get_for_member(self, organization_id: OrganizationID, account_id: uuid.UUID) -> Organization | None:
        org = self.organizations.get(organization_id)
        return org if org and org.has_member(account_id) else None

    @override
    async def list_for_account(
        self, account_id: uuid.UUID, *, limit: int = 10, offset: int = 0
    ) -> tuple[list[Organization], int]:
        matching = [org for org in self.organizations.values() if org.has_member(account_id)]
        return matching[offset : offset + limit], len(matching)

    @override
    async def list_pending_verification(self) -> list[Organization]:
        return [org for org in self.organizations.values() if org.verification_status == VerificationStatus.PENDING]

    @override
    @override
    async def save(self, organization: Organization) -> None:
        organization.version += 1
        self.organizations[organization.id] = organization
        self.outbox.extend(organization.pull_events())


class InMemoryPayoutAccountRepository(PayoutAccountRepository):
    def __init__(self, organization_repository: InMemoryOrganizationRepository) -> None:
        self._organization_repository = organization_repository
        self.payout_accounts: dict[PayoutAccountID, PayoutAccount] = {}
        self.outbox = organization_repository.outbox

    @override
    async def get(self, payout_account_id: PayoutAccountID) -> PayoutAccount | None:
        return self.payout_accounts.get(payout_account_id)

    @override
    async def list_pending_review(self) -> list[PayoutAccount]:
        return [payout for payout in self.payout_accounts.values() if payout.status == PayoutAccountStatus.PENDING]

    @override
    async def save(self, organization: Organization, *payout_accounts: PayoutAccount) -> None:
        organization.version += 1
        self._organization_repository.organizations[organization.id] = organization
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
def payout_repository(repository: InMemoryOrganizationRepository) -> InMemoryPayoutAccountRepository:
    return InMemoryPayoutAccountRepository(repository)


@pytest.fixture
def clock(now: datetime) -> FakeClock:
    return FakeClock(now)


@pytest.fixture
def service(repository: InMemoryOrganizationRepository, clock: FakeClock) -> OrganizationService:
    return OrganizationService(repository, clock)


@pytest.fixture
def payout_account_service(
    repository: InMemoryOrganizationRepository,
    payout_repository: InMemoryPayoutAccountRepository,
    clock: FakeClock,
) -> PayoutAccountService:
    return PayoutAccountService(repository, payout_repository, clock)


@pytest.fixture
def create_organization_with_legal_profile(service: OrganizationService, account_id: uuid.UUID):
    async def create() -> Organization:
        organization = await service.create(
            owner_account_id=account_id,
            public_name="Event Crew",
        )
        return await service.update_profile(
            organization.id,
            account_id,
            legal_profile=OrganizationLegalProfile("Maria da Silva", "529.982.247-25", TaxIDType.CPF),
        )

    return create
