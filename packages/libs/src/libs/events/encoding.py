import json
from abc import ABC, abstractmethod
from typing import override

from .event import Metadata, PublishableEvent


class Encoder(ABC):
    @abstractmethod
    def encode(self, event: PublishableEvent) -> str | bytes:
        pass


class JsonEncoder(Encoder):
    @override
    def encode(self, event: PublishableEvent) -> str:
        return json.dumps(
            {
                "name": event.NAME,
                "metadata": event.metadata.to_dict(),
                "payload": event.to_dict(),
            }
        )


class UnmappedEventError(Exception):
    def __init__(self, event_name: str):
        super().__init__(f"Event {event_name} does not have a mapped event class. Did you called load_events() before?")


class EventDecodeError(ValueError):
    """Raised when a message does not match the event envelope format."""


class Decoder(ABC):
    @abstractmethod
    def decode(self, data: str | bytes) -> PublishableEvent:
        """
        Raises:
            UnmappedEventError: if event does not have a mapped event class
        """
        pass


class JsonDecoder(Decoder):
    @override
    def decode(self, data: str | bytes) -> PublishableEvent:
        try:
            decoded = json.loads(data)
            if not isinstance(decoded, dict):
                raise TypeError("event envelope must be a JSON object")
            event_name = decoded["name"]
            metadata = Metadata.from_dict(decoded["metadata"])
            payload = decoded["payload"]
            if not isinstance(event_name, str) or not isinstance(payload, dict):
                raise TypeError("'name' must be a string and 'payload' must be an object")
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise EventDecodeError("Message is not a valid event envelope") from exc

        try:
            event_cls = PublishableEvent.for_name(event_name)
        except KeyError as e:
            raise UnmappedEventError(event_name) from e

        return event_cls.from_dict(payload, metadata)
