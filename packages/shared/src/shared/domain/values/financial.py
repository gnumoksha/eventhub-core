import re
from enum import StrEnum
from typing import Final


class PixKeyType(StrEnum):
    CPF = "CPF"
    CNPJ = "CNPJ"
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    EVP = "EVP"


class Pix:
    """
    Instant Payment (Pix) key used for receiving payments in Brazil.

    The key can be a CPF, CNPJ, phone number, email address, or EVP (End-to-End Verification Protocol) identifier.
    """

    KEY_MAX_LENGTH: Final[int] = 77

    def __init__(self, key: str, type_: PixKeyType) -> None:
        # https://aprendervalor.bcb.gov.br/content/estabilidadefinanceira/pix/API-DICT.html#tag/Entry
        patterns = {
            PixKeyType.CPF: r"[0-9]{11}",
            PixKeyType.CNPJ: r"[A-Z0-9]{12}[0-9]{2}",
            PixKeyType.PHONE: r"\+[1-9][0-9]{1,14}",
            PixKeyType.EMAIL: r"[a-z0-9.!#$'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*",
            PixKeyType.EVP: r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        }
        if len(key) > self.KEY_MAX_LENGTH or re.fullmatch(patterns[type_], key) is None:
            raise ValueError(f"Enter a valid Pix key for type {type_.value}")

        self.key = key
        self.type = type_
