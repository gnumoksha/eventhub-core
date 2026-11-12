from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Query, Response, status
from identity.infra.http.authentication import CommonSessionDep, CSRFDep
from pydantic import BaseModel
from shared.infra.http.pagination import PaginatedOutput

from organizers.application.organization.service import (
    OrganizationServiceDep,
)
from organizers.application.organization.values import (
    AddMemberInput,
    CreateOrganizationInput,
    PayoutAccountInput,
    UpdateOrganizationInput,
)
from organizers.application.payout_account.service import PayoutAccountServiceDep
from organizers.domain.models.organization.organization import Organization
from organizers.domain.models.organization.values import TaxIDType, mask_tax_identifier
from organizers.domain.models.payout_account.payout_account import PayoutAccount

router = APIRouter(prefix="/organizations", tags=["organizers"])


class MemberOutput(BaseModel):
    account_id: UUID
    role: str


class OrganizationOutput(BaseModel):
    id: UUID
    tax_id_type: TaxIDType | None
    public_name: str
    legal_name: str | None
    tax_id: str | None
    verification_status: str
    can_sell_paid_tickets: bool
    verification_rejection_reason: str | None
    members: list[MemberOutput]


class PayoutAccountOutput(BaseModel):
    id: UUID
    method: str
    status: str
    pix_key: str | None
    pix_type: str | None
    bank_code: str | None
    branch: str | None
    account_number: str | None
    account_digit: str | None
    account_type: str | None
    holder_name: str
    holder_tax_id: str
    rejection_reason: str | None


def _organization_output(
    organization: Organization, viewer_account_id: UUID
) -> OrganizationOutput:
    return OrganizationOutput(
        id=organization.id,
        tax_id_type=organization.tax_id_type,
        public_name=organization.public_name,
        legal_name=(
            organization.legal_name
            if organization.has_owner(viewer_account_id)
            else None
        ),
        tax_id=(
            mask_tax_identifier(organization.tax_id)
            if organization.tax_id is not None
            else None
        ),
        verification_status=organization.verification_status,
        can_sell_paid_tickets=organization.can_sell_paid_tickets,
        verification_rejection_reason=organization.verification_rejection_reason,
        members=[
            MemberOutput(account_id=member.account_id, role=member.role)
            for member in organization.members
        ],
    )


def _payout_output(payout_account: PayoutAccount) -> PayoutAccountOutput:
    return PayoutAccountOutput(
        id=payout_account.id,
        method=payout_account.method,
        status=payout_account.status,
        pix_key=_mask_value(payout_account.pix_key),
        pix_type=payout_account.pix_type,
        bank_code=_mask_value(payout_account.bank_code),
        branch=_mask_value(payout_account.branch),
        account_number=_mask_value(payout_account.account_number),
        account_digit=_mask_value(payout_account.account_digit),
        account_type=payout_account.account_type,
        holder_name=payout_account.holder_name,
        holder_tax_id=mask_tax_identifier(payout_account.holder_tax_id),
        rejection_reason=payout_account.rejection_reason,
    )


def _mask_value(value: str | None) -> str | None:
    if value is None:
        return None
    return (
        "*" * len(value) if len(value) <= 4 else f"{'*' * (len(value) - 4)}{value[-4:]}"
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_organization(
    input_: CreateOrganizationInput,
    service: OrganizationServiceDep,
    session: CommonSessionDep,
    _csrf: CSRFDep,
) -> OrganizationOutput:
    organization = await service.create(
        owner_account_id=session.account_id,
        public_name=input_.public_name,
    )
    return _organization_output(organization, session.account_id)


@router.get("")
async def list_organizations(
    service: OrganizationServiceDep,
    session: CommonSessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedOutput[OrganizationOutput]:
    organizations, total = await service.list_for_account(
        session.account_id, limit=limit, offset=offset
    )
    return PaginatedOutput(
        items=[_organization_output(org, session.account_id) for org in organizations],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{organization_id}")
async def get_organization(
    organization_id: UUID,
    service: OrganizationServiceDep,
    session: CommonSessionDep,
) -> OrganizationOutput:
    return _organization_output(
        await _get_organization(service, organization_id, session.account_id),
        session.account_id,
    )


@router.patch("/{organization_id}")
async def update_organization(
    organization_id: UUID,
    input_: UpdateOrganizationInput,
    service: OrganizationServiceDep,
    session: CommonSessionDep,
    _csrf: CSRFDep,
) -> OrganizationOutput:
    organization = await service.update_profile(
        organization_id,
        session.account_id,
        public_name=input_.public_name,
        legal_profile=input_.to_legal_profile(),
    )
    return _organization_output(organization, session.account_id)


@router.get("/{organization_id}/members")
async def list_members(
    organization_id: UUID,
    service: OrganizationServiceDep,
    session: CommonSessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedOutput[MemberOutput]:
    organization = await _get_organization(service, organization_id, session.account_id)
    all_members = [
        MemberOutput(account_id=member.account_id, role=member.role)
        for member in organization.members
    ]
    total = len(all_members)
    items = all_members[offset : offset + limit]
    return PaginatedOutput(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/{organization_id}/members", status_code=status.HTTP_201_CREATED)
async def add_member(
    organization_id: UUID,
    input_: AddMemberInput,
    service: OrganizationServiceDep,
    session: CommonSessionDep,
    _csrf: CSRFDep,
) -> list[MemberOutput]:
    organization = await service.add_member(
        organization_id, session.account_id, input_.account_id, input_.role
    )
    return [
        MemberOutput(account_id=member.account_id, role=member.role)
        for member in organization.members
    ]


@router.delete(
    "/{organization_id}/members/{member_account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    organization_id: UUID,
    member_account_id: UUID,
    service: OrganizationServiceDep,
    session: CommonSessionDep,
    _csrf: CSRFDep,
) -> Response:
    await service.remove_member(organization_id, session.account_id, member_account_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{organization_id}/verification", status_code=status.HTTP_202_ACCEPTED)
async def submit_verification(
    organization_id: UUID,
    service: OrganizationServiceDep,
    session: CommonSessionDep,
    _csrf: CSRFDep,
) -> OrganizationOutput:
    return _organization_output(
        await service.submit_verification(organization_id, session.account_id),
        session.account_id,
    )


@router.post("/{organization_id}/payout-account", status_code=status.HTTP_202_ACCEPTED)
async def submit_payout_account(
    organization_id: UUID,
    input_: Annotated[PayoutAccountInput, Body(discriminator="method")],
    service: PayoutAccountServiceDep,
    session: CommonSessionDep,
    _csrf: CSRFDep,
) -> PayoutAccountOutput:
    payout_account = await service.submit(
        organization_id,
        session.account_id,
        details=input_.to_domain(),
    )
    return _payout_output(payout_account)


@router.get("/{organization_id}/payout-account")
async def get_payout_account(
    organization_id: UUID,
    service: PayoutAccountServiceDep,
    session: CommonSessionDep,
) -> dict[str, PayoutAccountOutput | None]:
    current, pending = await service.get_for_organization(
        organization_id, session.account_id
    )
    return {
        "current": _payout_output(current) if current else None,
        "pending": _payout_output(pending) if pending else None,
    }


async def _get_organization(
    service: OrganizationServiceDep, organization_id: UUID, account_id: UUID
) -> Organization:
    return await service.get(organization_id, account_id)
