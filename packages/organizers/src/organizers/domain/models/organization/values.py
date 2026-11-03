import re
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from shared.domain.errors import InvalidValue

OrganizationID = uuid.UUID
AccountID = uuid.UUID
NAME_MAX_LENGTH = 200
REJECTION_REASON_MAX_LENGTH = 500
_CPF_LENGTH = 11
_CPF_CHECK_DIGIT_ROLLOVER = 10


@dataclass(frozen=True)
class Name:
    value: str
    label: ClassVar[str] = "Name"

    def __post_init__(self) -> None:
        value = self.value.strip()
        if not value or len(value) > NAME_MAX_LENGTH:
            raise InvalidValue(f"{self.label} must contain between 1 and {NAME_MAX_LENGTH} characters")
        object.__setattr__(self, "value", value)


class PublicName(Name):
    label = "Public name"


class LegalName(Name):
    label = "Legal name"


@dataclass(frozen=True)
class RejectionReason:
    value: str

    def __post_init__(self) -> None:
        value = self.value.strip()
        if not value or len(value) > REJECTION_REASON_MAX_LENGTH:
            raise InvalidValue(
                f"The rejection reason must contain between 1 and {REJECTION_REASON_MAX_LENGTH} characters"
            )
        object.__setattr__(self, "value", value)


class OrganizationVerificationRejectionReason(RejectionReason):
    pass


class TaxIDType(StrEnum):
    CPF = "CPF"
    CNPJ = "CNPJ"


class MemberRole(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    STAFF = "STAFF"
    CHECKIN_OPERATOR = "CHECKIN_OPERATOR"


class VerificationStatus(StrEnum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class TaxIdentifier:
    def __init__(self, value: str, tax_id_type: TaxIDType) -> None:
        value = re.sub(r"[.\-/\s]", "", value).upper()
        if tax_id_type is TaxIDType.CPF:
            if not _valid_cpf(value):
                raise InvalidValue("Enter a valid CPF")
        elif not _valid_cnpj(value):
            raise InvalidValue("Enter a valid CNPJ")
        self.value = value


@dataclass(frozen=True)
class OrganizationLegalProfile:
    legal_name: str
    tax_id: str
    tax_id_type: TaxIDType

    def __post_init__(self) -> None:
        object.__setattr__(self, "legal_name", LegalName(self.legal_name).value)
        object.__setattr__(self, "tax_id", TaxIdentifier(self.tax_id, self.tax_id_type).value)


def _valid_cpf(value: str) -> bool:
    if not value.isdigit() or len(value) != _CPF_LENGTH or len(set(value)) == 1:
        return False
    digits = [int(char) for char in value]
    first = (sum(digit * weight for digit, weight in zip(digits[:9], range(10, 1, -1), strict=True)) * 10) % 11
    if first == _CPF_CHECK_DIGIT_ROLLOVER:
        first = 0
    second = (sum(digit * weight for digit, weight in zip(digits[:10], range(11, 1, -1), strict=True)) * 10) % 11
    if second == _CPF_CHECK_DIGIT_ROLLOVER:
        second = 0
    return digits[9:] == [first, second]


def _valid_cnpj(value: str) -> bool:
    if not re.fullmatch(r"[A-Z0-9]{12}\d{2}", value) or len(set(value)) == 1:
        return False
    values = [ord(char) - 48 if char.isalpha() else int(char) for char in value[:12]]
    first = _cnpj_digit(values)
    second = _cnpj_digit([*values, first])
    return value[-2:] == f"{first}{second}"


def _cnpj_digit(values: list[int]) -> int:
    weights = (2, 3, 4, 5, 6, 7, 8, 9)
    total = sum(value * weights[index % 8] for index, value in enumerate(reversed(values)))
    remainder = total % 11
    return 0 if remainder in (0, 1) else 11 - remainder


def mask_tax_identifier(value: str) -> str:
    return f"{'*' * (len(value) - 4)}{value[-4:]}"
