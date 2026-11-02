from cryptography.fernet import Fernet
from pydantic import SecretStr
from shared.infra.encryption.sqlalchemy import EncryptedString
from sqlalchemy.dialects.postgresql import dialect


def test_encrypted_string_does_not_store_plaintext():
    field = EncryptedString(SecretStr(Fernet.generate_key().decode()))

    stored = field.process_bind_param("52998224725", dialect())

    assert stored is not None
    assert "52998224725" not in stored
    assert field.process_result_value(stored, dialect()) == "52998224725"
