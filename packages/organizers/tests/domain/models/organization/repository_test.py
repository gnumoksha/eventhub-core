from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from organizers.domain.models.organization.organization import Organization
from organizers.domain.models.organization.repository import OrganizationRepository
from organizers.domain.models.organization.values import OrganizationID, OrganizationProfile, OrganizationType
from pydantic import SecretStr
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
def repository(session: AsyncSession) -> OrganizationRepository:
    return OrganizationRepository(session)


@pytest.fixture
def organization() -> Organization:
    return Organization.create(
        profile=OrganizationProfile(
            OrganizationType.INDIVIDUAL,
            "Event Crew",
            "Maria da Silva",
            "52998224725",
        ),
        owner_account_id=OrganizationID("018d0e91-3d0b-7000-8000-000000000001"),
        now=NOW,
    )


async def test_round_trip_and_ciphertext_storage(
    repository: OrganizationRepository, session: AsyncSession, organization: Organization
):
    await repository.save(organization)

    loaded = await repository.get(organization.id)
    assert loaded is not None
    assert loaded.tax_id == "52998224725"
    assert loaded.members[0].account_id == organization.members[0].account_id
    assert loaded.version == 1

    result = await session.execute(
        text("SELECT tax_id, legal_name FROM organizers.organizations WHERE id = :organization_id"),
        {"organization_id": organization.id},
    )
    encrypted_tax_id, encrypted_legal_name = result.one()
    assert encrypted_tax_id != "52998224725"
    assert encrypted_legal_name != "Maria da Silva"


async def test_creation_events_are_saved_to_outbox_atomically(
    repository: OrganizationRepository, session: AsyncSession, organization: Organization
):
    await repository.save(organization)

    result = await session.execute(select(OutboxMessage))
    outbox = result.scalars().all()
    event_names = [
        row.event_name for row in outbox if row.message["payload"].get("organization_id") == str(organization.id)
    ]
    assert event_names == ["eventhub.organizers.organization.created", "eventhub.organizers.member.added"]
    assert organization.pull_events() == []
