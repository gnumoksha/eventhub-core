# The events dispatched by this domain model.

from typing import Self, override

from libs.events import Metadata, PublishableEvent, SerializableDict
from shared.infra.domain_events import DomainEventsConfig

from events.domain.models.event.entity import EventID


class EventWasCreated(PublishableEvent, name="eventhub:events:event.was_created"):
    def __init__(
        self,
        event_id: EventID,
        metadata: Metadata | None = None,
    ) -> None:
        super().__init__(DomainEventsConfig(), metadata)

        self.event_id = event_id

    @override
    def to_dict(self) -> SerializableDict:
        return {
            "event_id": str(self.event_id),
        }

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(
            event_id=EventID(str(payload["event_id"])),
            metadata=metadata,
        )
