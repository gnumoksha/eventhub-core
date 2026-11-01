import uuid

import pytest
from organizers.domain.models.organization.events import MemberAdded, MemberRemoved, OrganizationVerified
from organizers.domain.models.organization.organization import Organization
from organizers.domain.models.organization.values import (
    MemberRole,
    OrganizationProfile,
    OrganizationType,
    TaxIdentifier,
    VerificationStatus,
)
from shared.domain.errors import InvalidStateTransition, InvalidValue

from tests.conftest import NOW


def make_organization(owner_account_id: uuid.UUID | None = None) -> Organization:
    return Organization.create(
        profile=OrganizationProfile(OrganizationType.INDIVIDUAL, "Event Crew", "Maria da Silva", "52998224725"),
        owner_account_id=owner_account_id or uuid.uuid4(),
        now=NOW,
    )


def test_creation_assigns_owner_and_records_events():
    account_id = uuid.uuid4()
    organization = make_organization(account_id)

    assert organization.members[0].account_id == account_id
    assert organization.members[0].role == MemberRole.OWNER
    assert organization.verification_status == VerificationStatus.NOT_SUBMITTED
    assert len(organization.pull_events()) == 2


def test_rejects_removal_of_last_owner():
    organization = make_organization()

    with pytest.raises(InvalidStateTransition, match="at least one owner"):
        organization.remove_member(organization.members[0].account_id, now=NOW)


def test_owner_can_remove_member_and_records_event():
    organization = make_organization()
    account_id = uuid.uuid4()
    organization.add_member(account_id, MemberRole.STAFF, now=NOW)
    organization.pull_events()

    organization.remove_member(account_id, now=NOW)

    [event] = organization.pull_events()
    assert isinstance(event, MemberRemoved)
    assert event.account_id == account_id


def test_kyc_must_be_submitted_before_approval():
    organization = make_organization()
    organization.pull_events()

    with pytest.raises(InvalidStateTransition):
        organization.verify(now=NOW)

    organization.submit_verification(now=NOW)
    organization.verify(now=NOW)
    [event] = organization.pull_events()
    assert isinstance(event, OrganizationVerified)
    assert organization.verification_status == VerificationStatus.VERIFIED


def test_rejected_kyc_can_be_corrected_and_resubmitted():
    organization = make_organization()
    organization.submit_verification(now=NOW)
    organization.reject_verification("Document mismatch", now=NOW)
    organization.update_legal_profile("Maria Silva", "52998224725", now=NOW)
    organization.submit_verification(now=NOW)

    assert organization.verification_status == VerificationStatus.PENDING
    assert organization.verification_rejection_reason is None


@pytest.mark.parametrize("tax_id", ["12345678900", "11111111111", "52998224724"])
def test_rejects_invalid_cpf(tax_id: str):
    with pytest.raises(InvalidValue):
        TaxIdentifier(tax_id, OrganizationType.INDIVIDUAL)


def test_accepts_alphanumeric_cnpj_from_receita_federal_example():
    # Receita Federal/SERPRO example: 12.ABC.345/01DE-35.
    assert TaxIdentifier("12.ABC.345/01DE-35", OrganizationType.COMPANY).value == "12ABC34501DE35"


def test_rejects_invalid_cnpj_check_digits():
    with pytest.raises(InvalidValue):
        TaxIdentifier("12.ABC.345/01DE-34", OrganizationType.COMPANY)


def test_member_added_event_round_trips():
    organization = make_organization()
    organization.pull_events()
    account_id = uuid.uuid4()
    organization.add_member(account_id, MemberRole.CHECKIN_OPERATOR, now=NOW)
    [added] = organization.pull_events()

    assert isinstance(added, MemberAdded)
    restored = MemberAdded.from_dict(added.to_dict(), added.metadata)
    assert restored.to_dict() == added.to_dict()
