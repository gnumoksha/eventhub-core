from typing import Self, override

from libs.events import Metadata, PublishableEvent, SerializableDict
from shared.infra.domain_events import DomainEventsConfig

from identity.domain.models.customer.customer import CustomerID


class CustomerLoggedIn(PublishableEvent, name="eventhub:identity:customer.logged_in"):
    def __init__(
        self,
        customer_id: CustomerID,
        is_new_customer: bool,
        metadata: Metadata | None = None,
    ) -> None:
        super().__init__(DomainEventsConfig(), metadata)

        self.customer_id = customer_id
        self.is_new_customer = is_new_customer

    @override
    def to_dict(self) -> SerializableDict:
        return {
            "user_id": str(self.customer_id),
            "is_new_customer": self.is_new_customer,
        }

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(
            customer_id=CustomerID(str(payload["customer_id"])),
            is_new_customer=bool(payload["is_new_customer"]),
            metadata=metadata,
        )
