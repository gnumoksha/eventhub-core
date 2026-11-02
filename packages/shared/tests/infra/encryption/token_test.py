from shared.infra.encryption.token import (
    decrypt_authentication_token,
    encrypt_authentication_token,
)


def test_email_credential_token_is_encrypted_before_delivery() -> None:
    raw_token = "one-time-authentication-token"
    encrypted = encrypt_authentication_token(raw_token)

    assert encrypted != raw_token
    assert decrypt_authentication_token(encrypted) == raw_token
