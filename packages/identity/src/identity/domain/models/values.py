from dataclasses import dataclass
from typing import ClassVar, Self

from shared.domain.errors import InvalidValue


@dataclass(frozen=True, slots=True)
class Email:
    value: str

    MAX_LEN: ClassVar[int] = 320

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", self._validate(self.value))

    @classmethod
    def from_trusted(cls, value: str) -> Self:
        email = cls.__new__(cls)
        object.__setattr__(email, "value", value)
        return email

    @classmethod
    def _validate(cls, email: str) -> str:
        """
        Raises:
            - ValueError
        """
        value = email.strip().casefold()
        if len(value) > cls.MAX_LEN or value.count("@") != 1:
            raise InvalidValue("Enter a valid email address")

        local, domain = value.rsplit("@", 1)
        if not local or not domain or "." not in domain or any(char.isspace() for char in value):
            raise InvalidValue("Enter a valid email address")

        return value


@dataclass(frozen=True, slots=True)
class Password:
    value: str

    MIN_LEN: ClassVar[int] = 8
    MAX_LEN: ClassVar[int] = 128

    def __post_init__(self) -> None:
        if len(self.value) < self.MIN_LEN:
            raise InvalidValue(f"Password must contain at least {self.MIN_LEN} characters")
        if len(self.value) > self.MAX_LEN:
            raise InvalidValue(f"Password must contain at most {self.MAX_LEN} characters")

    @classmethod
    def from_trusted(cls, value: str) -> Self:
        password = cls.__new__(cls)
        object.__setattr__(password, "value", value)
        return password
