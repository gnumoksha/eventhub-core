from typing import Self, override

from libs.events import Metadata, PublishableEvent, SerializableDict

from identity.domain.models.account.account import AccountID


class AccountLoggedIn(PublishableEvent, name="eventhub.identity.account.logged_in"):
    def __init__(
        self,
        account_id: AccountID,
        is_new_account: bool,
        metadata: Metadata | None = None,
    ) -> None:
        super().__init__(metadata)

        self.account_id = account_id
        self.is_new_account = is_new_account

    @override
    def to_dict(self) -> SerializableDict:
        return {
            "account_id": str(self.account_id),
            "is_new_account": self.is_new_account,
        }

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(
            account_id=AccountID(str(payload["account_id"])),
            is_new_account=bool(payload["is_new_account"]),
            metadata=metadata,
        )


class AccountVerificationRequested(PublishableEvent, name="eventhub.identity.account.verification_requested"):
    def __init__(self, email: str, encrypted_token: str, metadata: Metadata | None = None) -> None:
        super().__init__(metadata)
        self.email = email
        self.encrypted_token = encrypted_token

    @override
    def to_dict(self) -> SerializableDict:
        return {"email": self.email, "encrypted_token": self.encrypted_token}

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(email=str(payload["email"]), encrypted_token=str(payload["encrypted_token"]), metadata=metadata)


class PasswordResetRequested(PublishableEvent, name="eventhub.identity.password_reset_requested"):
    def __init__(self, email: str, encrypted_token: str, metadata: Metadata | None = None) -> None:
        super().__init__(metadata)
        self.email = email
        self.encrypted_token = encrypted_token

    @override
    def to_dict(self) -> SerializableDict:
        return {"email": self.email, "encrypted_token": self.encrypted_token}

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(email=str(payload["email"]), encrypted_token=str(payload["encrypted_token"]), metadata=metadata)
