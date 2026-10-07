import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Self

import uuid_utils.compat as uuid_compat

SerializableDict = dict[str, str | int | float | bool | None]


class Config(ABC):
    @property
    @abstractmethod
    def exchange(self) -> str:
        """The exchange (topic in Kafka terminology) name to publish to"""
        pass

    @property
    @abstractmethod
    def queue(self) -> str:
        """The queue name to publish to"""
        pass

    @property
    @abstractmethod
    def routing_key(self) -> str:
        """
        The message routing key.

        Useful when using direct or topic exchanges in RabbitMQ.
        """
        pass


class Metadata:
    def __init__(
        self,
        schema_version: str = "1.0.0",
        id: uuid.UUID | None = None,
        occurred_on: datetime | None = None,
    ) -> None:
        self._schema_version = schema_version
        self._id = id or uuid_compat.uuid7()
        self._occurred_on = occurred_on or datetime.now(UTC)

    @property
    def id(self) -> uuid.UUID:
        """
        Returns the event's ID.

        This can be useful to identify the event in the Event Store,
        debugging, etc.
        """
        return self._id

    @property
    def occurred_on(self) -> datetime:
        """Returns the time where the event did happen."""
        return self._occurred_on

    def to_dict(self) -> SerializableDict:
        """
        Returns a dictionary representation of the event.
        This will be used to serialize the event to JSON and send it to the queue.
        """
        return {
            "id": str(self._id),
            "occurred_on": self._occurred_on.isoformat(),
            "schema_version": self._schema_version,
        }

    @classmethod
    def from_dict(cls, metadata: SerializableDict) -> Self:
        """
        Populates the event's attributes from a dictionary representation.
        This will be used to deserialize the event from JSON received from the queue.
        """
        return cls(
            str(metadata["schema_version"]),
            uuid.UUID(str(metadata["id"])),
            datetime.fromisoformat(str(metadata["occurred_on"])),
        )


class PublishableEvent(ABC):
    """
    Describes a significant event that did happen on the Domain and will be
    published to a messaging system.
    The event must be relevant to the business.

    Examples:
     - UserWasCreated (if the Domain cares about every instance of a new User)
     - UserWasSaved (if the Domain cares about every User persisted on the database)
     - PurchaseMadeByCustomer (if the Domain cares about every purchase a customer makes)

    If an Event throws an exception, it will go to a special queue where it will be
    analyzed and, eventually, processed again. So, sometimes it is useful to use
    events in order to get the benefits of restarting a failed event. But you
    must keep in mind that all event listeners must be idempotent,
    i.e. they must not process an already processed event.
    """

    NAME: str
    """The event name"""

    _registry: dict[str, type[Self]] = {}
    """Contains the event's name and its class"""

    def __init_subclass__(cls, name: str, **kwargs):
        """
        Args:
          - name: the event name
        """
        super().__init_subclass__(**kwargs)

        cls.NAME = name
        PublishableEvent._registry[name] = cls

    def __init__(self, config: Config, metadata: Metadata | None):
        self.config = config
        self.metadata = metadata or Metadata()

    @classmethod
    def name(cls) -> str:
        """
        Returns a unique name for the event.

        This name will be used to register subscribers using the
        publish/subscribe pattern."""
        return cls.NAME

    @classmethod
    def for_name(cls, name: str) -> type[Self]:
        """
        Given the event name, returns the correspondent class.

        If this method raises an error, it may means you forgot to call load_events()

        Raises:
            - KeyError: if event name is not registered
        """
        return cls._registry[name]

    @abstractmethod
    def to_dict(self) -> SerializableDict:
        """
        Returns a dictionary representation of the event.
        This will be used to serialize the event to JSON and send it to the queue.
        """
        pass

    @classmethod
    @abstractmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        """
        Populates the event's attributes from a dictionary representation.
        This will be used to deserialize the event from JSON received from the queue.
        """
        pass
