from typing import Self, override
from unittest import TestCase

from libs.events import Metadata, PublishableEvent, SerializableDict, SyncDispatcher, listener
from shared.infra.domain_events import DomainEventsConfig


class SomeEventOccurred(PublishableEvent, name="test:some_event_occurred"):
    def __init__(
        self,
        some_field: str,
        metadata: Metadata | None = None,
    ) -> None:
        super().__init__(DomainEventsConfig(), metadata)
        self.some_field = some_field

    @override
    def to_dict(self) -> SerializableDict:
        return {
            "some_field": self.some_field,
        }

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(
            str(payload["some_field"]),
            metadata,
        )


class TestEverything(TestCase):
    @override
    def setUp(self) -> None:
        self._dispatcher = SyncDispatcher()

    def test_dispatch_and_listener(self):
        called = False

        @listener(SomeEventOccurred)
        def listener_func(event: SomeEventOccurred):
            nonlocal called
            called = True
            assert event.name() == "test:some_event_occurred"

        event = SomeEventOccurred("some_value")
        self._dispatcher.dispatch(event)
        assert called
