from datetime import datetime
from typing import Any, Self

import uuid_utils.compat as uuid_compat
from libs.events import PublishableEvent
from pydantic import PrivateAttr
from shared.domain.errors import InvalidStateTransition, InvalidValue
from shared.domain.values.financial import PixKeyType
from shared.infra.encryption.sqlalchemy import EncryptedString
from shared.settings import settings
from sqlalchemy import Enum
from sqlalchemy.orm import declared_attr, reconstructor
from sqlmodel import Field, SQLModel

from organizers.domain.models.organization.values import (
    REJECTION_REASON_MAX_LENGTH,
    OrganizationID,
    TaxIdentifier,
    TaxIDType,
)
from organizers.domain.models.payout_account.events import PayoutAccountVerified
from organizers.domain.models.payout_account.values import (
    BankPayoutDetails,
    PayoutAccountHolderName,
    PayoutAccountID,
    PayoutAccountRejectionReason,
    PayoutAccountStatus,
    PayoutMethod,
    PixPayoutDetails,
)


class PayoutAccount(SQLModel, table=True):
    __tablename__: str = "payout_accounts"
    __table_args__ = {"schema": "organizers"}

    id: PayoutAccountID = Field(default_factory=uuid_compat.uuid7, primary_key=True)
    organization_id: OrganizationID = Field(foreign_key="organizers.organizations.id", index=True)
    method: PayoutMethod = Field(sa_type=Enum(PayoutMethod, inherit_schema=True))
    status: PayoutAccountStatus = Field(
        default=PayoutAccountStatus.PENDING,
        sa_type=Enum(PayoutAccountStatus, inherit_schema=True),
        index=True,
    )
    pix_key: str | None = Field(default=None, sa_type=EncryptedString(settings.PERSONAL_DATA_ENCRYPTION_KEY))
    pix_type: PixKeyType | None = Field(default=None, sa_type=Enum(PixKeyType, inherit_schema=True))
    bank_code: str | None = Field(default=None, sa_type=EncryptedString(settings.PERSONAL_DATA_ENCRYPTION_KEY))
    branch: str | None = Field(default=None, sa_type=EncryptedString(settings.PERSONAL_DATA_ENCRYPTION_KEY))
    account_number: str | None = Field(default=None, sa_type=EncryptedString(settings.PERSONAL_DATA_ENCRYPTION_KEY))
    account_digit: str | None = Field(default=None, sa_type=EncryptedString(settings.PERSONAL_DATA_ENCRYPTION_KEY))
    account_type: str | None = Field(default=None, max_length=32)
    holder_name: str = Field(sa_type=EncryptedString(settings.PERSONAL_DATA_ENCRYPTION_KEY))
    holder_tax_id: str = Field(sa_type=EncryptedString(settings.PERSONAL_DATA_ENCRYPTION_KEY))
    rejection_reason: str | None = Field(default=None, max_length=REJECTION_REASON_MAX_LENGTH)
    created_at: datetime
    updated_at: datetime
    version: int = 0

    _pending_events: list[PublishableEvent] = PrivateAttr(default_factory=list)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:  # noqa: N805
        return {"version_id_col": cls.__table__.c.version}  # ty:ignore[unresolved-attribute]

    @reconstructor
    def _init_on_load(self) -> None:
        self.__pydantic_private__ = {"_pending_events": []}

    @classmethod
    def create_pix(
        cls,
        *,
        organization_id: OrganizationID,
        tax_id_type: TaxIDType,
        details: PixPayoutDetails,
        now: datetime,
    ) -> Self:
        holder_tax_id = TaxIdentifier(details.holder_tax_id, tax_id_type).value
        return cls(
            organization_id=organization_id,
            method=PayoutMethod.PIX,
            status=PayoutAccountStatus.PENDING,
            pix_key=details.pix.key,
            pix_type=details.pix.type,
            holder_name=PayoutAccountHolderName(details.holder_name).value,
            holder_tax_id=holder_tax_id,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def create_bank_transfer(
        cls,
        *,
        organization_id: OrganizationID,
        tax_id_type: TaxIDType,
        details: BankPayoutDetails,
        now: datetime,
    ) -> Self:
        values = (
            details.bank_code.strip(),
            details.branch.strip(),
            details.account_number.strip(),
            details.account_digit.strip(),
        )
        if any(not value for value in values):
            raise InvalidValue("Bank code, branch, account number and digit are required")
        account_type = details.account_type.strip().upper()
        if account_type not in {"CHECKING", "SAVINGS"}:
            raise InvalidValue("Account type must be CHECKING or SAVINGS")
        holder_tax_id = TaxIdentifier(details.holder_tax_id, tax_id_type).value
        return cls(
            organization_id=organization_id,
            method=PayoutMethod.BANK_TRANSFER,
            status=PayoutAccountStatus.PENDING,
            bank_code=values[0],
            branch=values[1],
            account_number=values[2],
            account_digit=values[3],
            account_type=account_type,
            holder_name=PayoutAccountHolderName(details.holder_name).value,
            holder_tax_id=holder_tax_id,
            created_at=now,
            updated_at=now,
        )

    def verify(self, *, now: datetime) -> None:
        if self.status != PayoutAccountStatus.PENDING:
            raise InvalidStateTransition("Only a pending payout account can be approved")

        self.status = PayoutAccountStatus.VERIFIED
        self.rejection_reason = None
        self.updated_at = now
        self._record(PayoutAccountVerified(self.organization_id, self.id))

    def reject(self, reason: str, *, now: datetime) -> None:
        if self.status != PayoutAccountStatus.PENDING:
            raise InvalidStateTransition("Only a pending payout account can be rejected")

        self.status = PayoutAccountStatus.REJECTED
        self.rejection_reason = PayoutAccountRejectionReason(reason).value
        self.updated_at = now

    def supersede(self, *, now: datetime) -> None:
        if self.status != PayoutAccountStatus.VERIFIED:
            raise InvalidStateTransition("Only a verified payout account can be replaced")

        self.status = PayoutAccountStatus.SUPERSEDED
        self.updated_at = now

    def pull_events(self) -> list[PublishableEvent]:
        events, self._pending_events = self._pending_events, []
        return events

    def _record(self, event: PublishableEvent) -> None:
        self._pending_events.append(event)
