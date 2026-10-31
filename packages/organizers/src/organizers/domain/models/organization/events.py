from typing import Self, override

from libs.events import Metadata, PublishableEvent, SerializableDict

from organizers.domain.models.organization.values import AccountID, MemberRole, OrganizationID, PayoutAccountID


class OrganizationCreated(PublishableEvent, name="eventhub.organizers.organization.created"):
    def __init__(self, organization_id: OrganizationID, public_name: str, metadata: Metadata | None = None) -> None:
        super().__init__(metadata)
        self.organization_id = organization_id
        self.public_name = public_name

    @override
    def to_dict(self) -> SerializableDict:
        return {"organization_id": str(self.organization_id), "public_name": self.public_name}

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(OrganizationID(str(payload["organization_id"])), str(payload["public_name"]), metadata)


class MemberAdded(PublishableEvent, name="eventhub.organizers.member.added"):
    def __init__(
        self, organization_id: OrganizationID, account_id: AccountID, role: MemberRole, metadata: Metadata | None = None
    ) -> None:
        super().__init__(metadata)
        self.organization_id = organization_id
        self.account_id = account_id
        self.role = role

    @override
    def to_dict(self) -> SerializableDict:
        return {
            "organization_id": str(self.organization_id),
            "account_id": str(self.account_id),
            "role": self.role.value,
        }

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(
            OrganizationID(str(payload["organization_id"])),
            AccountID(str(payload["account_id"])),
            MemberRole(str(payload["role"])),
            metadata,
        )


class MemberRemoved(PublishableEvent, name="eventhub.organizers.member.removed"):
    def __init__(
        self, organization_id: OrganizationID, account_id: AccountID, metadata: Metadata | None = None
    ) -> None:
        super().__init__(metadata)
        self.organization_id = organization_id
        self.account_id = account_id

    @override
    def to_dict(self) -> SerializableDict:
        return {"organization_id": str(self.organization_id), "account_id": str(self.account_id)}

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(OrganizationID(str(payload["organization_id"])), AccountID(str(payload["account_id"])), metadata)


class OrganizationVerified(PublishableEvent, name="eventhub.organizers.organization.verified"):
    def __init__(self, organization_id: OrganizationID, metadata: Metadata | None = None) -> None:
        super().__init__(metadata)
        self.organization_id = organization_id

    @override
    def to_dict(self) -> SerializableDict:
        return {"organization_id": str(self.organization_id)}

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(OrganizationID(str(payload["organization_id"])), metadata)


class PayoutAccountVerified(PublishableEvent, name="eventhub.organizers.payout_account.verified"):
    def __init__(
        self,
        organization_id: OrganizationID,
        payout_account_id: PayoutAccountID,
        metadata: Metadata | None = None,
    ) -> None:
        super().__init__(metadata)
        self.organization_id = organization_id
        self.payout_account_id = payout_account_id

    @override
    def to_dict(self) -> SerializableDict:
        return {"organization_id": str(self.organization_id), "payout_account_id": str(self.payout_account_id)}

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(
            OrganizationID(str(payload["organization_id"])),
            PayoutAccountID(str(payload["payout_account_id"])),
            metadata,
        )
