from typing import Self, override

from libs.events import Metadata, PublishableEvent, SerializableDict

from organizers.domain.models.organization.values import OrganizationID
from organizers.domain.models.payout_account.values import PayoutAccountID


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
