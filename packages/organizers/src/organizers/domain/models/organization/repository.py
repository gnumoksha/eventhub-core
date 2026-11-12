from typing import Annotated

from shared.domain.errors import ConcurrencyConflict
from shared.infra.database.sql import SessionDep
from shared.infra.di import Depends
from shared.infra.outbox import add_to_outbox
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import StaleDataError
from sqlmodel import col, func, select

from organizers.domain.models.organization.organization import Member, Organization
from organizers.domain.models.organization.values import (
    AccountID,
    OrganizationID,
    VerificationStatus,
)


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, organization_id: OrganizationID) -> Organization | None:
        query = (
            select(Organization)
            .where(col(Organization.id) == organization_id)
            .options(selectinload(Organization.members))  # ty:ignore[invalid-argument-type]
        )
        result = await self._session.execute(query)
        return result.scalars().first()

    async def get_for_member(self, organization_id: OrganizationID, account_id: AccountID) -> Organization | None:
        query = (
            select(Organization)
            .join(Member, col(Organization.id) == col(Member.organization_id))
            .where(col(Organization.id) == organization_id, col(Member.account_id) == account_id)
            .options(selectinload(Organization.members))  # ty:ignore[invalid-argument-type]
        )
        result = await self._session.execute(query)
        return result.scalars().first()

    async def list_for_account(self, account_id: AccountID) -> list[Organization]:
        query = (
            select(Organization)
            .join(Member, col(Organization.id) == col(Member.organization_id))
            .where(col(Member.account_id) == account_id)
            .options(selectinload(Organization.members))  # ty:ignore[invalid-argument-type]
            .order_by(col(Organization.created_at), col(Organization.id))
        )
        result = await self._session.execute(query)
        return list(result.scalars().unique().all())

    async def list_paginated_for_account(
        self, account_id: AccountID, *, limit: int = 10, offset: int = 0
    ) -> tuple[list[Organization], int]:
        count_query = (
            select(func.count(func.distinct(col(Organization.id))))
            .join(Member, col(Organization.id) == col(Member.organization_id))
            .where(col(Member.account_id) == account_id)
        )
        total_res = await self._session.execute(count_query)
        total = total_res.scalar_one_or_none() or 0

        query = (
            select(Organization)
            .join(Member, col(Organization.id) == col(Member.organization_id))
            .where(col(Member.account_id) == account_id)
            .options(selectinload(Organization.members))  # ty:ignore[invalid-argument-type]
            .order_by(col(Organization.created_at), col(Organization.id))
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(query)
        return list(result.scalars().unique().all()), total

    async def list_pending_verification(self) -> list[Organization]:
        query = (
            select(Organization)
            .where(col(Organization.verification_status) == VerificationStatus.PENDING)
            .options(selectinload(Organization.members))  # ty:ignore[invalid-argument-type]
            .order_by(col(Organization.created_at), col(Organization.id))
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def save(self, organization: Organization) -> None:
        organization_id = organization.id
        self._session.add(organization)

        add_to_outbox(self._session, organization.pull_events())

        try:
            await self._session.commit()
        except StaleDataError as exc:
            await self._session.rollback()
            raise ConcurrencyConflict(f"Organization {organization_id} was modified by someone else") from exc


async def __get_repository(session: SessionDep) -> OrganizationRepository:
    return OrganizationRepository(session)


OrganizationRepositoryDep = Annotated[OrganizationRepository, Depends(__get_repository)]
