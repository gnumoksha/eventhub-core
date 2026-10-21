import uuid
from datetime import UTC, datetime
from enum import StrEnum

import uuid_utils.compat as uuid_compat
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

AccountID = uuid.UUID


class Account(SQLModel, table=True):
    __tablename__: str = "accounts"
    __table_args__ = (
        UniqueConstraint("email", name="uq_identity_accounts_email"),
        {"schema": "identity"},
    )

    id: AccountID = Field(default_factory=uuid_compat.uuid7, primary_key=True)
    email: str = Field(max_length=320)
    password_hash: str = Field(max_length=512)
    email_verified_at: datetime | None = None
    deactivated_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Session(SQLModel, table=True):
    __tablename__: str = "sessions"
    __table_args__ = {"schema": "identity"}

    id: uuid.UUID = Field(default_factory=uuid_compat.uuid7, primary_key=True)
    account_id: AccountID = Field(foreign_key="identity.accounts.id", index=True)
    token_hash: str = Field(max_length=64, unique=True, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    revoked_at: datetime | None = None


class CredentialPurpose(StrEnum):
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"  # noqa: S105


class AccountCredential(SQLModel, table=True):
    __tablename__: str = "account_credentials"
    __table_args__ = {"schema": "identity"}

    id: uuid.UUID = Field(default_factory=uuid_compat.uuid7, primary_key=True)
    account_id: AccountID = Field(foreign_key="identity.accounts.id", index=True)
    purpose: str = Field(max_length=32, index=True)
    token_hash: str = Field(max_length=64, unique=True, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    consumed_at: datetime | None = None
