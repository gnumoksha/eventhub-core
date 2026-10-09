from abc import ABC, abstractmethod
from datetime import datetime

from events.domain.models.event.event import Event
from events.domain.models.event.values import EventID, EventStatus, OrganizationID


class EventRepository(ABC):
    @abstractmethod
    def get(self, id: EventID) -> Event | None:
        pass

    @abstractmethod
    def save(self, event: Event) -> None:
        """
        Inserts or updates the event and, in the same transaction, stores its
        pending integration events to be published.

        Raises:
            ConcurrencyConflict: if the event was modified since it was loaded.
        """

    @abstractmethod
    def list_by_organization(
        self,
        organization_id: OrganizationID,
        *,
        status: EventStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Event]:
        pass

    @abstractmethod
    def list_ended_but_not_finished(self, now: datetime, *, limit: int) -> list[Event]:
        """Returns published or postponed events whose period already ended."""
