from typing import Self, override

from libs.events import Metadata, PublishableEvent, SerializableDict
from shared.infra.domain_events import DomainEventsConfig

from identity.domain.models.user.user import UserId


class UserLoggedIn(PublishableEvent, name="eventhub:identity:user.logged_in"):
    def __init__(
        self,
        user_id: UserId,
        is_new_user: bool,
        metadata: Metadata | None = None,
    ) -> None:
        super().__init__(DomainEventsConfig(), metadata)

        self.user_id = user_id
        self.is_new_user = is_new_user

    @override
    def to_dict(self) -> SerializableDict:
        return {
            "user_id": str(self.user_id),
            "is_new_user": self.is_new_user,
        }

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(
            user_id=UserId(str(payload["user_id"])),
            is_new_user=bool(payload["is_new_user"]),
            metadata=metadata,
        )
