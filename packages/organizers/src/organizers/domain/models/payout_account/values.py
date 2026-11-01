import uuid
from dataclasses import dataclass
from enum import StrEnum

from shared.domain.values.financial import Pix

PayoutAccountID = uuid.UUID


class PayoutMethod(StrEnum):
    PIX = "PIX"
    BANK_TRANSFER = "BANK_TRANSFER"


class PayoutAccountStatus(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class PixPayoutDetails:
    pix: Pix
    holder_name: str
    holder_tax_id: str


@dataclass(frozen=True)
class BankPayoutDetails:
    bank_code: str
    branch: str
    account_number: str
    account_digit: str
    account_type: str
    holder_name: str
    holder_tax_id: str
