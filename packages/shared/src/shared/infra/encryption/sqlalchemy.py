from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr
from sqlalchemy import Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class EncryptedString(TypeDecorator[str]):
    """Encrypts a string column with the supplied Fernet key."""

    impl = Text
    # The secret must not be included in SQLAlchemy's statement cache key.
    cache_ok = False

    def __init__(self, secret: SecretStr) -> None:
        super().__init__()
        self._secret = secret

    def _cipher(self) -> Fernet:
        try:
            return Fernet(self._secret.get_secret_value().encode())
        except (ValueError, TypeError) as exc:
            raise RuntimeError("The encryption secret must be a valid Fernet key") from exc

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        _ = dialect
        if value is None:
            return None
        return self._cipher().encrypt(value.encode()).decode()

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        _ = dialect
        if value is None:
            return None
        try:
            return self._cipher().decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise RuntimeError("Could not decrypt value; check the Fernet key") from exc

    def process_literal_param(self, value: str | None, dialect: Dialect) -> str:
        return self.process_bind_param(value, dialect) or "NULL"
