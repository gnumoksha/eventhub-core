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
        decoded = json.loads(data)
        event_name = decoded["name"]
        metadata = Metadata.from_dict(decoded["metadata"])
        payload = decoded["payload"]

        try:
            event_cls = PublishableEvent.for_name(event_name)
        except KeyError as e:
            raise UnmappedEventError(event_name) from e

        return event_cls.from_dict(payload, metadata)
