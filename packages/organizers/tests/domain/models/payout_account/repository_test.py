from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from organizers.domain.models.organization.organization import Organization
from organizers.domain.models.organization.repository import OrganizationRepository
from organizers.domain.models.organization.values import OrganizationID, OrganizationLegalProfile, TaxIDType
from organizers.domain.models.payout_account.payout_account import PayoutAccount
from organizers.domain.models.payout_account.repository import PayoutAccountRepository
from organizers.domain.models.payout_account.values import PayoutAccountStatus, PixPayoutDetails
from pydantic import SecretStr
from shared.domain.values.financial import Pix, PixKeyType
from shared.infra.database import engine
from shared.infra.outbox import OutboxMessage
from shared.settings import settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from sqlmodel import select

from tests.conftest import NOW

pytestmark = [pytest.mark.database_access, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def connection() -> AsyncIterator[AsyncConnection]:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        yield connection
        await transaction.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def session(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    ) as session:
        yield session


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PERSONAL_DATA_ENCRYPTION_KEY", SecretStr(Fernet.generate_key().decode()))


@pytest.fixture
def organization_repository(session: AsyncSession) -> OrganizationRepository:
    return OrganizationRepository(session)


@pytest.fixture
def payout_account_repository(session: AsyncSession) -> PayoutAccountRepository:
    return PayoutAccountRepository(session)


@pytest.fixture
def organization() -> Organization:
    organization = Organization.create(
        public_name="Event Crew",
        owner_account_id=OrganizationID("018d0e91-3d0b-7000-8000-000000000001"),
        now=NOW,
    )
    organization.update_legal_profile(OrganizationLegalProfile("Maria da Silva", "52998224725", TaxIDType.CPF), now=NOW)
    return organization


@pytest.fixture
def payout_account(organization: Organization) -> PayoutAccount:
    return PayoutAccount.create_pix(
        organization_id=organization.id,
        tax_id_type=TaxIDType.CPF,
        details=PixPayoutDetails(Pix("maria@example.com", PixKeyType.EMAIL), "Maria da Silva", "52998224725"),
        now=NOW,
    )


async def test_saves_payout_account_and_verified_event_atomically(
    organization_repository: OrganizationRepository,
    payout_account_repository: PayoutAccountRepository,
    session: AsyncSession,
    organization: Organization,
    payout_account: PayoutAccount,
):
    await organization_repository.save(organization)
    payout_account.verify(now=NOW)
    organization.current_payout_account_id = payout_account.id

    await payout_account_repository.save(organization, payout_account)

    loaded = await payout_account_repository.get(payout_account.id)
    assert loaded is not None
    assert loaded.status == PayoutAccountStatus.VERIFIED
    assert loaded.pix_key == "maria@example.com"
    assert loaded.pix_type == PixKeyType.EMAIL
    assert organization.current_payout_account_id == loaded.id

    outbox = (await session.execute(select(OutboxMessage))).scalars().all()
    assert any(message.event_name == "eventhub.organizers.payout_account.verified" for message in outbox)
    stored_pix_key = await session.execute(
        text("SELECT pix_key FROM organizers.payout_accounts WHERE id = :payout_account_id"),
        {"payout_account_id": payout_account.id},
    )
    assert stored_pix_key.scalar_one() != "maria@example.com"


async def test_lists_only_pending_payout_accounts(
    organization_repository: OrganizationRepository,
    payout_account_repository: PayoutAccountRepository,
    organization: Organization,
    payout_account: PayoutAccount,
):
    await organization_repository.save(organization)
    verified = PayoutAccount.create_pix(
        organization_id=organization.id,
        tax_id_type=TaxIDType.CPF,
        details=PixPayoutDetails(Pix("verified@example.com", PixKeyType.EMAIL), "Maria da Silva", "52998224725"),
        now=NOW,
    )
    verified.verify(now=NOW)

    await payout_account_repository.save(organization, payout_account, verified)

    assert await payout_account_repository.list_pending_review() == [payout_account]
