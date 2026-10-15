from typing import Self, override

from libs.events.dispatcher import RecordingDispatcher, SyncDispatcher
from libs.events.event import Metadata, PublishableEvent, SerializableDict
from libs.events.listener import _listeners, listener

from tests.conftest import DummyConfig


class EventA(PublishableEvent, name="test:event_a"):
    def __init__(self, val: str, metadata: Metadata | None = None) -> None:
        super().__init__(DummyConfig(), metadata)
        self.val = val

    @override
    def to_dict(self) -> SerializableDict:
        return {"val": self.val}

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(str(payload["val"]), metadata)


class EventB(PublishableEvent, name="test:event_b"):
    def __init__(self, metadata: Metadata | None = None) -> None:
        super().__init__(DummyConfig(), metadata)

    @override
    def to_dict(self) -> SerializableDict:
        return {}

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(metadata)


class TestDispatcherAndListeners:
    def test_sync_dispatcher_invokes_registered_listener(self):
        called_with: list[str] = []

        @listener(EventA)
        def on_event_a(event: EventA) -> None:
            called_with.append(event.val)

        dispatcher = SyncDispatcher()
        event = EventA("first")
        dispatcher.dispatch(event)

        assert called_with == ["first"]

    def test_sync_dispatcher_invokes_multiple_listeners(self):
        log: list[str] = []

        @listener(EventA)
        def listener_1(event: EventA) -> None:
            log.append(f"l1:{event.val}")

        @listener(EventA)
        def listener_2(event: EventA) -> None:
            log.append(f"l2:{event.val}")

        dispatcher = SyncDispatcher()
        dispatcher.dispatch(EventA("multi"))

        assert log == ["l1:multi", "l2:multi"]

    def test_sync_dispatcher_with_no_listeners_does_not_fail(self, caplog):
        dispatcher = SyncDispatcher()
        event = EventB()

        # Should log warning and not raise error
        with caplog.at_level("WARNING"):
            dispatcher.dispatch(event)

        assert "No listeners registered for event: test:event_b" in caplog.text

    def test_recording_dispatcher_stores_dispatched_events(self):
        dispatcher = RecordingDispatcher()
        event1 = EventA("x")
        event2 = EventB()

        dispatcher.dispatch(event1)
        dispatcher.dispatch(event2)

        assert dispatcher.dispatched == [event1, event2]

    def test_listener_decorator_registers_function_in_dict(self):
        assert "test:event_a" not in _listeners

        @listener(EventA)
        def my_listener(event: EventA) -> None:
            pass

        assert my_listener in _listeners["test:event_a"]
