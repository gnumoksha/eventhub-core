# The events dispatched by this domain model.

from datetime import datetime
from typing import Self, override

from libs.events import Metadata, PublishableEvent, SerializableDict
from shared.infra.domain_events import DomainEventsConfig

from events.domain.models.event.values import EventID, OrganizationID


class EventPublished(PublishableEvent, name="eventhub:events:event.published"):
    def __init__(  # noqa: PLR0913
        self,
        *,
        event_id: EventID,
        organization_id: OrganizationID,
        title: str,
        start_at: datetime,
        end_at: datetime,
        metadata: Metadata | None = None,
    ) -> None:
        super().__init__(DomainEventsConfig(), metadata)

        self.event_id = event_id
        self.organization_id = organization_id
        self.title = title
        self.start_at = start_at
        self.end_at = end_at

    @override
    def to_dict(self) -> SerializableDict:
        return {
            "event_id": str(self.event_id),
            "organization_id": str(self.organization_id),
            "title": self.title,
            "start_at": self.start_at.isoformat(),
            "end_at": self.end_at.isoformat(),
        }

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(
            event_id=EventID(str(payload["event_id"])),
            organization_id=OrganizationID(str(payload["organization_id"])),
            title=str(payload["title"]),
            start_at=datetime.fromisoformat(str(payload["start_at"])),
            end_at=datetime.fromisoformat(str(payload["end_at"])),
            metadata=metadata,
        )


class EventPostponed(PublishableEvent, name="eventhub:events:event.postponed"):
    def __init__(  # noqa: PLR0913
        self,
        *,
        event_id: EventID,
        organization_id: OrganizationID,
        start_at: datetime,
        end_at: datetime,
        previous_start_at: datetime,
        previous_end_at: datetime,
        metadata: Metadata | None = None,
    ) -> None:
        super().__init__(DomainEventsConfig(), metadata)

        self.event_id = event_id
        self.organization_id = organization_id
        self.start_at = start_at
        self.end_at = end_at
        self.previous_start_at = previous_start_at
        self.previous_end_at = previous_end_at

    @override
    def to_dict(self) -> SerializableDict:
        return {
            "event_id": str(self.event_id),
            "organization_id": str(self.organization_id),
            "start_at": self.start_at.isoformat(),
            "end_at": self.end_at.isoformat(),
            "previous_start_at": self.previous_start_at.isoformat(),
            "previous_end_at": self.previous_end_at.isoformat(),
        }

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(
            event_id=EventID(str(payload["event_id"])),
            organization_id=OrganizationID(str(payload["organization_id"])),
            start_at=datetime.fromisoformat(str(payload["start_at"])),
            end_at=datetime.fromisoformat(str(payload["end_at"])),
            previous_start_at=datetime.fromisoformat(str(payload["previous_start_at"])),
            previous_end_at=datetime.fromisoformat(str(payload["previous_end_at"])),
            metadata=metadata,
        )


class EventCancelled(PublishableEvent, name="eventhub:events:event.cancelled"):
    def __init__(
        self,
        *,
        event_id: EventID,
        organization_id: OrganizationID,
        reason: str,
        metadata: Metadata | None = None,
    ) -> None:
        super().__init__(DomainEventsConfig(), metadata)

        self.event_id = event_id
        self.organization_id = organization_id
        self.reason = reason

    @override
    def to_dict(self) -> SerializableDict:
        return {
            "event_id": str(self.event_id),
            "organization_id": str(self.organization_id),
            "reason": self.reason,
        }

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(
            event_id=EventID(str(payload["event_id"])),
            organization_id=OrganizationID(str(payload["organization_id"])),
            reason=str(payload["reason"]),
            metadata=metadata,
        )


class EventFinished(PublishableEvent, name="eventhub:events:event.finished"):
    def __init__(
        self,
        *,
        event_id: EventID,
        organization_id: OrganizationID,
        end_at: datetime,
        metadata: Metadata | None = None,
    ) -> None:
        super().__init__(DomainEventsConfig(), metadata)

        self.event_id = event_id
        self.organization_id = organization_id
        self.end_at = end_at

    @override
    def to_dict(self) -> SerializableDict:
        return {
            "event_id": str(self.event_id),
            "organization_id": str(self.organization_id),
            "end_at": self.end_at.isoformat(),
        }

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(
            event_id=EventID(str(payload["event_id"])),
            organization_id=OrganizationID(str(payload["organization_id"])),
            end_at=datetime.fromisoformat(str(payload["end_at"])),
            metadata=metadata,
        )
