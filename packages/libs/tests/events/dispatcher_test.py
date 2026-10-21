from typing import Self, override

import pytest
from libs.events.dispatcher import LocalDispatcher, RecordingDispatcher
from libs.events.event import Metadata, PublishableEvent, SerializableDict
from libs.events.listener import _listeners, listened_event_names, listener


class EventA(PublishableEvent, name="test.event_a"):
    def __init__(self, val: str, metadata: Metadata | None = None) -> None:
        super().__init__(metadata)
        self.val = val

    @override
    def to_dict(self) -> SerializableDict:
        return {"val": self.val}

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(str(payload["val"]), metadata)


class EventB(PublishableEvent, name="test.event_b"):
    def __init__(self, metadata: Metadata | None = None) -> None:
        super().__init__(metadata)

    @override
    def to_dict(self) -> SerializableDict:
        return {}

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(metadata)


@pytest.mark.asyncio
class TestDispatcherAndListeners:
    async def test_local_dispatcher_invokes_registered_listener(self):
        called_with: list[str] = []

        @listener(EventA)
        async def on_event_a(event: EventA) -> None:
            called_with.append(event.val)

        dispatcher = LocalDispatcher()
        event = EventA("first")
        await dispatcher.dispatch(event)

        assert called_with == ["first"]

    async def test_local_dispatcher_invokes_multiple_listeners_in_order(self):
        log: list[str] = []

        @listener(EventA)
        async def listener_1(event: EventA) -> None:
            log.append(f"l1:{event.val}")

        @listener(EventA)
        async def listener_2(event: EventA) -> None:
            log.append(f"l2:{event.val}")

        dispatcher = LocalDispatcher()
        await dispatcher.dispatch(EventA("multi"))

        assert log == ["l1:multi", "l2:multi"]

    async def test_local_dispatcher_stops_at_the_first_failing_listener(self):
        log: list[str] = []

        @listener(EventA)
        async def failing(event: EventA) -> None:
            raise RuntimeError(event.val)

        @listener(EventA)
        async def never_called(event: EventA) -> None:
            log.append(event.val)

        with pytest.raises(RuntimeError, match="boom"):
            await LocalDispatcher().dispatch(EventA("boom"))

        assert log == []

    async def test_local_dispatcher_with_no_listeners_does_not_fail(self, caplog):
        dispatcher = LocalDispatcher()
        event = EventB()

        with caplog.at_level("WARNING"):
            await dispatcher.dispatch(event)

        assert "No listeners registered for event: test.event_b" in caplog.text
        assert "obsolete binding" in caplog.text

    async def test_recording_dispatcher_stores_dispatched_events(self):
        dispatcher = RecordingDispatcher()
        event1 = EventA("x")
        event2 = EventB()

        await dispatcher.dispatch(event1)
        await dispatcher.dispatch(event2)

        assert dispatcher.dispatched == [event1, event2]


class TestListener:
    def test_listener_decorator_registers_function_in_dict(self):
        assert "test.event_a" not in _listeners

        @listener(EventA)
        async def my_listener(event: EventA) -> None:
            pass

        assert my_listener in _listeners["test.event_a"]
        assert listened_event_names() == ["test.event_a"]

    def test_listener_decorator_rejects_sync_functions(self):
        with pytest.raises(TypeError, match="must be an async function"):

            @listener(EventA)
            def sync_listener(event: EventA) -> None:  # ty: ignore[invalid-argument-type]
                pass

        assert listened_event_names() == []
