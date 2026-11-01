from datetime import datetime
from typing import Any, Self

import uuid_utils.compat as uuid_compat
from libs.events import PublishableEvent
from pydantic import PrivateAttr
from shared.domain.errors import InvalidStateTransition, InvalidValue
from shared.infra.encryption.sqlalchemy import EncryptedString
from shared.settings import settings
from sqlalchemy import Enum
from sqlalchemy.orm import declared_attr, reconstructor
from sqlmodel import Field, Relationship, SQLModel

from organizers.domain.models.organization.events import (
    MemberAdded,
    MemberRemoved,
    OrganizationCreated,
    OrganizationVerified,
)
from organizers.domain.models.organization.validation import (
    NAME_MAX_LENGTH,
    REJECTION_REASON_MAX_LENGTH,
    _validate_name,
    _validate_rejection_reason,
)
from organizers.domain.models.organization.values import (
    AccountID,
    MemberRole,
    OrganizationID,
    OrganizationProfile,
    OrganizationType,
    TaxIdentifier,
    VerificationStatus,
)
from organizers.domain.models.payout_account.values import PayoutAccountID


class Organization(SQLModel, table=True):
    __tablename__: str = "organizations"
    __table_args__ = {"schema": "organizers"}

    id: OrganizationID = Field(default_factory=uuid_compat.uuid7, primary_key=True)
    organization_type: OrganizationType = Field(sa_type=Enum(OrganizationType, inherit_schema=True))
    public_name: str = Field(max_length=NAME_MAX_LENGTH)
    legal_name: str = Field(sa_type=EncryptedString(settings.PERSONAL_DATA_ENCRYPTION_KEY))
    tax_id: str = Field(sa_type=EncryptedString(settings.PERSONAL_DATA_ENCRYPTION_KEY))
    verification_status: VerificationStatus = Field(
        default=VerificationStatus.NOT_SUBMITTED,
        sa_type=Enum(VerificationStatus, inherit_schema=True),
        index=True,
    )
    verification_rejection_reason: str | None = Field(default=None, max_length=REJECTION_REASON_MAX_LENGTH)
    current_payout_account_id: PayoutAccountID | None = None
    pending_payout_account_id: PayoutAccountID | None = None
    created_at: datetime
    updated_at: datetime
    version: int = 0

    members: list[Member] = Relationship(
        back_populates="organization",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "lazy": "selectin"},
    )

    _pending_events: list[PublishableEvent] = PrivateAttr(default_factory=list)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:  # noqa: N805
        return {"version_id_col": cls.__table__.c.version}  # ty:ignore[unresolved-attribute]

    @reconstructor
    def _init_on_load(self) -> None:
        self.__pydantic_private__ = {"_pending_events": []}

    @classmethod
    def create(
        cls,
        *,
        profile: OrganizationProfile,
        owner_account_id: AccountID,
        now: datetime,
    ) -> Self:
        public_name = _validate_name(profile.public_name, "Public name")
        legal_name = _validate_name(profile.legal_name, "Legal name")
        tax_id = TaxIdentifier(profile.tax_id, profile.organization_type).value
        organization = cls(
            organization_type=profile.organization_type,
            public_name=public_name,
            legal_name=legal_name,
            tax_id=tax_id,
            verification_status=VerificationStatus.NOT_SUBMITTED,
            created_at=now,
            updated_at=now,
        )
        organization.members.append(
            Member(organization_id=organization.id, account_id=owner_account_id, role=MemberRole.OWNER)
        )
        organization._record(OrganizationCreated(organization.id, organization.public_name))
        organization._record(MemberAdded(organization.id, owner_account_id, MemberRole.OWNER))
        return organization

    def has_member(self, account_id: AccountID) -> bool:
        return any(member.account_id == account_id for member in self.members)

    def has_owner(self, account_id: AccountID) -> bool:
        return any(member.account_id == account_id and member.role == MemberRole.OWNER for member in self.members)

    @property
    def can_sell_paid_tickets(self) -> bool:
        return self.verification_status == VerificationStatus.VERIFIED and self.current_payout_account_id is not None

    def add_member(self, account_id: AccountID, role: MemberRole, *, now: datetime) -> None:
        if self.has_member(account_id):
            raise InvalidValue("This account is already a member of the organization")

        self.members.append(Member(organization_id=self.id, account_id=account_id, role=role))
        self._touch(now)
        self._record(MemberAdded(self.id, account_id, role))

    def remove_member(self, account_id: AccountID, *, now: datetime) -> None:
        member = next((member for member in self.members if member.account_id == account_id), None)
        if member is None:
            raise InvalidValue("The account is not a member of the organization")

        if member.role == MemberRole.OWNER and sum(m.role == MemberRole.OWNER for m in self.members) <= 1:
            raise InvalidStateTransition("An organization must always have at least one owner")

        self.members.remove(member)
        self._touch(now)
        self._record(MemberRemoved(self.id, account_id))

    def update_public_name(self, public_name: str, *, now: datetime) -> None:
        self.public_name = _validate_name(public_name, "Public name")
        self._touch(now)

    def update_legal_profile(self, legal_name: str, tax_id: str, *, now: datetime) -> None:
        if self.verification_status not in (VerificationStatus.NOT_SUBMITTED, VerificationStatus.REJECTED):
            raise InvalidStateTransition("Legal details can only be changed before submission or after rejection")

        self.legal_name = _validate_name(legal_name, "Legal name")
        self.tax_id = TaxIdentifier(tax_id, self.organization_type).value
        self._touch(now)

    def submit_verification(self, *, now: datetime) -> None:
        if self.verification_status not in (VerificationStatus.NOT_SUBMITTED, VerificationStatus.REJECTED):
            raise InvalidStateTransition(
                "Verification can only be submitted when it has not been submitted or was rejected"
            )

        self.verification_status = VerificationStatus.PENDING
        self.verification_rejection_reason = None
        self._touch(now)

    def verify(self, *, now: datetime) -> None:
        if self.verification_status != VerificationStatus.PENDING:
            raise InvalidStateTransition("Only pending verification can be approved")

        self.verification_status = VerificationStatus.VERIFIED
        self.verification_rejection_reason = None
        self._touch(now)
        self._record(OrganizationVerified(self.id))

    def reject_verification(self, reason: str, *, now: datetime) -> None:
        if self.verification_status != VerificationStatus.PENDING:
            raise InvalidStateTransition("Only pending verification can be rejected")

        self.verification_status = VerificationStatus.REJECTED
        self.verification_rejection_reason = _validate_rejection_reason(reason)
        self._touch(now)

    def pull_events(self) -> list[PublishableEvent]:
        events, self._pending_events = self._pending_events, []
        return events

    def _record(self, event: PublishableEvent) -> None:
        self._pending_events.append(event)

    def _touch(self, now: datetime) -> None:
        self.updated_at = now


class Member(SQLModel, table=True):
    __tablename__: str = "members"
    __table_args__ = {"schema": "organizers"}

    organization_id: OrganizationID = Field(foreign_key="organizers.organizations.id", primary_key=True)
    account_id: AccountID = Field(primary_key=True, index=True)
    role: MemberRole = Field(sa_type=Enum(MemberRole, inherit_schema=True), index=True)
    organization: Organization = Relationship(back_populates="members")
