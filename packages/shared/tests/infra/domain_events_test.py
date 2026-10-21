from collections.abc import Iterator
from typing import Self, override
from unittest.mock import AsyncMock, MagicMock

import pytest
from aio_pika import ExchangeType
from libs.events import Metadata, PublishableEvent, SerializableDict, listener
from libs.events.listener import _listeners
from shared.infra.domain_events import EXCHANGE, declare_context_queue, declare_events_exchange

pytestmark = pytest.mark.asyncio


class SomethingListened(PublishableEvent, name="test.domain_events.something_listened"):
    def __init__(self, metadata: Metadata | None = None) -> None:
        super().__init__(metadata)

    @override
    def to_dict(self) -> SerializableDict:
        return {}

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(metadata)


@pytest.fixture(autouse=True)
def clean_listeners() -> Iterator[None]:
    yield
    _listeners.clear()


def make_exchange(name: str, *args, **kwargs) -> MagicMock:
    exchange = MagicMock()
    exchange.name = name  # MagicMock(name=...) names the mock instead of setting the attribute
    return exchange


class FakeChannel:
    """Records the declared exchanges and queues; every queue is a mock with an async bind()."""

    def __init__(self) -> None:
        self.declare_exchange = AsyncMock(side_effect=make_exchange)
        self.declare_queue = AsyncMock(side_effect=self._declare_queue)
        self.queues: dict[str, MagicMock] = {}

    def _declare_queue(self, name: str, **_kwargs) -> MagicMock:
        self.queues[name] = MagicMock(bind=AsyncMock())
        return self.queues[name]


def make_channel() -> FakeChannel:
    return FakeChannel()


async def test_events_exchange_is_a_topic_with_an_alternate_exchange_for_unrouted_events():
    channel = make_channel()

    await declare_events_exchange(channel)  # ty: ignore[invalid-argument-type]

    channel.declare_exchange.assert_any_await(
        EXCHANGE, ExchangeType.TOPIC, durable=True, arguments={"alternate-exchange": f"{EXCHANGE}.unrouted"}
    )
    channel.declare_exchange.assert_any_await(f"{EXCHANGE}.unrouted", ExchangeType.FANOUT, durable=True)
    unrouted_queue = channel.declare_queue.await_args_list[0]
    assert unrouted_queue.args == (f"{EXCHANGE}.unrouted",)
    assert {"x-message-ttl", "x-max-length"} <= unrouted_queue.kwargs["arguments"].keys()


async def test_context_queue_is_bound_only_to_the_events_with_listeners():
    @listener(SomethingListened)
    async def on_something(event: SomethingListened) -> None:
        pass

    channel = make_channel()

    await declare_context_queue(channel, "sales")  # ty: ignore[invalid-argument-type]

    queue_names = [call.args[0] for call in channel.declare_queue.await_args_list]
    assert queue_names == ["sales.events.dlq", f"{EXCHANGE}.unrouted", "sales.events"]
    main_queue = channel.declare_queue.await_args_list[-1]
    assert main_queue.kwargs["arguments"]["x-dead-letter-exchange"] == "sales.events.dlx"
    bind = channel.queues["sales.events"].bind
    bind.assert_awaited_once()
    assert bind.await_args.kwargs == {"routing_key": "test.domain_events.something_listened"}


async def test_context_queue_without_listeners_has_no_bindings():
    channel = make_channel()

    await declare_context_queue(channel, "checkin")  # ty: ignore[invalid-argument-type]

    channel.queues["checkin.events"].bind.assert_not_awaited()
