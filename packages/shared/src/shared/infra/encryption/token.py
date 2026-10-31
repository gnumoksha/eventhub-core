import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from shared.settings import settings


def encrypt_authentication_token(token: str) -> str:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.APP_SECRET.get_secret_value().encode()).digest())
    return Fernet(key).encrypt(token.encode()).decode()


def decrypt_authentication_token(encrypted_token: str) -> str:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.APP_SECRET.get_secret_value().encode()).digest())
    try:
        return Fernet(key).decrypt(encrypted_token.encode()).decode()
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise ValueError("Invalid encrypted authentication token") from exc
