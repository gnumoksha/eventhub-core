import uuid
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator
from shared.domain.errors import InvalidValue
from shared.domain.values.financial import Pix, PixKeyType

from organizers.domain.models.organization.values import (
    MemberRole,
    OrganizationLegalProfile,
    TaxIdentifier,
    TaxIDType,
)
from organizers.domain.models.payout_account.values import BankPayoutDetails, PayoutMethod, PixPayoutDetails


class CreateOrganizationInput(BaseModel):
    public_name: str = Field(min_length=1, max_length=200)


class UpdateOrganizationInput(BaseModel):
    public_name: str | None = Field(default=None, min_length=1, max_length=200)
    legal_name: str | None = Field(default=None, min_length=1, max_length=200)
    tax_id_type: TaxIDType | None = None
    tax_id: str | None = Field(default=None, min_length=11, max_length=18)

    @field_validator("tax_id")
    @classmethod
    def validate_tax_id(cls, value: str | None, info: ValidationInfo) -> str | None:
        tax_id_type = info.data.get("tax_id_type")
        if value is None or tax_id_type is None:
            return value

        try:
            return TaxIdentifier(value, tax_id_type).value
        except InvalidValue as exc:
            raise ValueError(exc.message) from exc

    @model_validator(mode="after")
    def require_updates(self):
        if self.public_name is None and self.legal_name is None and self.tax_id_type is None and self.tax_id is None:
            raise ValueError("At least one field must be updated")
        legal_profile = (self.legal_name, self.tax_id_type, self.tax_id)
        if any(value is not None for value in legal_profile) and any(value is None for value in legal_profile):
            raise ValueError("Legal name, tax ID type and tax ID must be updated together")
        return self

    def to_legal_profile(self) -> OrganizationLegalProfile | None:
        if self.legal_name is None:
            return None
        if self.tax_id is None or self.tax_id_type is None:
            raise ValueError("Legal name, tax ID type and tax ID must be updated together")
        return OrganizationLegalProfile(
            legal_name=self.legal_name,
            tax_id=self.tax_id,
            tax_id_type=self.tax_id_type,
        )


class AddMemberInput(BaseModel):
    account_id: uuid.UUID
    role: MemberRole


class PixPayoutInput(BaseModel):
    method: Literal[PayoutMethod.PIX] = PayoutMethod.PIX
    pix_key: str = Field(min_length=1, max_length=200)
    pix_key_type: PixKeyType
    holder_name: str = Field(min_length=1, max_length=200)
    holder_tax_id: str = Field(min_length=11, max_length=18)

    def to_domain(self) -> PixPayoutDetails:
        try:
            pix = Pix(self.pix_key, self.pix_key_type)
        except ValueError as exc:
            raise InvalidValue(str(exc)) from exc
        return PixPayoutDetails(pix, self.holder_name, self.holder_tax_id)


class BankPayoutInput(BaseModel):
    method: Literal[PayoutMethod.BANK_TRANSFER] = PayoutMethod.BANK_TRANSFER
    bank_code: str = Field(min_length=1, max_length=20)
    branch: str = Field(min_length=1, max_length=20)
    account_number: str = Field(min_length=1, max_length=30)
    account_digit: str = Field(min_length=1, max_length=5)
    account_type: str = Field(min_length=1, max_length=32)
    holder_name: str = Field(min_length=1, max_length=200)
    holder_tax_id: str = Field(min_length=11, max_length=18)

    def to_domain(self) -> BankPayoutDetails:
        return BankPayoutDetails(
            self.bank_code,
            self.branch,
            self.account_number,
            self.account_digit,
            self.account_type,
            self.holder_name,
            self.holder_tax_id,
        )


PayoutAccountInput = PixPayoutInput | BankPayoutInput
