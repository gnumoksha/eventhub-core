import uuid
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator
from shared.domain.errors import InvalidValue

from organizers.domain.models.organization.values import (
    BankPayoutDetails,
    MemberRole,
    OrganizationType,
    PayoutMethod,
    PixPayoutDetails,
    TaxIdentifier,
)


class CreateOrganizationInput(BaseModel):
    organization_type: OrganizationType
    public_name: str = Field(min_length=1, max_length=200)
    legal_name: str = Field(min_length=1, max_length=200)
    tax_id: str = Field(min_length=11, max_length=18)

    @field_validator("tax_id")
    @classmethod
    def validate_tax_id(cls, value: str, info: ValidationInfo) -> str:
        organization_type = info.data.get("organization_type")
        if organization_type is None:
            return value

        try:
            return TaxIdentifier(value, organization_type).value
        except InvalidValue as exc:
            raise ValueError(exc.message) from exc


class UpdateOrganizationInput(BaseModel):
    public_name: str | None = Field(default=None, min_length=1, max_length=200)
    legal_name: str | None = Field(default=None, min_length=1, max_length=200)
    tax_id: str | None = Field(default=None, min_length=11, max_length=18)

    @model_validator(mode="after")
    def require_updates(self):
        if self.public_name is None and self.legal_name is None and self.tax_id is None:
            raise ValueError("At least one field must be updated")
        if (self.legal_name is None) != (self.tax_id is None):
            raise ValueError("Legal name and tax ID must be updated together")
        return self


class AddMemberInput(BaseModel):
    account_id: uuid.UUID
    role: MemberRole


class PixPayoutInput(BaseModel):
    method: Literal[PayoutMethod.PIX] = PayoutMethod.PIX
    pix_key: str = Field(min_length=1, max_length=200)
    holder_name: str = Field(min_length=1, max_length=200)
    holder_tax_id: str = Field(min_length=11, max_length=18)

    def to_domain(self) -> PixPayoutDetails:
        return PixPayoutDetails(self.pix_key, self.holder_name, self.holder_tax_id)


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
