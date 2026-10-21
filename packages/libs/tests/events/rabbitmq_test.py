import asyncio
import signal
from typing import Self, override
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aio_pika import DeliveryMode
from aio_pika.exceptions import AMQPConnectionError, ChannelInvalidStateError, DeliveryError, PublishError
from libs.events.dispatcher import Dispatcher, EventDispatchError
from libs.events.encoding import EventDecodeError, JsonEncoder, UnmappedEventError
from libs.events.event import Metadata, PublishableEvent, SerializableDict
from libs.events.rabbitmq import (
    RabbitMQConnection,
    RabbitMQDispatcher,
    RabbitMQGracefulConsumer,
)
from pamqp.commands import Basic

pytestmark = pytest.mark.asyncio


class RabbitSampleEvent(PublishableEvent, name="test.rabbit_event"):
    def __init__(self, data: str, metadata: Metadata | None = None) -> None:
        super().__init__(metadata)
        self.data = data

    @override
    def to_dict(self) -> SerializableDict:
        return {"data": self.data}

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(str(payload["data"]), metadata)


def make_connection(channel: MagicMock | None = None) -> MagicMock:
    connection = MagicMock(spec=RabbitMQConnection)
    connection.channel = AsyncMock(return_value=channel or MagicMock())
    connection.close = AsyncMock()
    return connection


def make_message(body: bytes = b"body", delivery_tag: int = 1) -> MagicMock:
    message = MagicMock(body=body, delivery_tag=delivery_tag)
    message.ack = AsyncMock()
    message.nack = AsyncMock()
    return message


class TestRabbitMQConnection:
    @patch("libs.events.rabbitmq.aio_pika.connect_robust", new_callable=AsyncMock)
    async def test_connection_creation_with_params(self, mock_connect):
        conn = RabbitMQConnection("amqp://guest:guest@localhost:5672/", connection_name="my_worker")

        channel = await conn.channel()

        mock_connect.assert_awaited_once_with(
            "amqp://guest:guest@localhost:5672/", client_properties={"connection_name": "my_worker"}
        )
        mock_connect.return_value.channel.assert_awaited_once_with(publisher_confirms=True, on_return_raises=True)
        assert channel == mock_connect.return_value.channel.return_value

    @patch("libs.events.rabbitmq.aio_pika.connect_robust", new_callable=AsyncMock)
    async def test_channel_cached_while_open(self, mock_connect):
        mock_connect.return_value.is_closed = False
        mock_connect.return_value.channel.return_value = MagicMock(is_closed=False)
        conn = RabbitMQConnection("amqp://localhost")

        assert await conn.channel() is await conn.channel()
        assert mock_connect.await_count == 1
        assert mock_connect.return_value.channel.await_count == 1

    @patch("libs.events.rabbitmq.aio_pika.connect_robust", new_callable=AsyncMock)
    async def test_listeners_called_only_on_first_channel(self, mock_connect):
        mock_connect.return_value.is_closed = False
        ch1 = MagicMock(is_closed=False)
        ch2 = MagicMock(is_closed=False)
        mock_connect.return_value.channel.side_effect = [ch1, ch2]
        conn = RabbitMQConnection("amqp://localhost")
        received: list[MagicMock] = []

        async def my_listener(ch):
            received.append(ch)

        conn.on_first_channel(my_listener)
        assert await conn.channel() is ch1
        ch1.is_closed = True
        assert await conn.channel() is ch2

        assert received == [ch1]

    @patch("libs.events.rabbitmq.aio_pika.connect_robust", new_callable=AsyncMock)
    async def test_listeners_called_again_if_they_failed(self, mock_connect):
        mock_connect.return_value.is_closed = False
        conn = RabbitMQConnection("amqp://localhost")
        listener = AsyncMock(side_effect=[AMQPConnectionError("down"), None])
        conn.on_first_channel(listener)

        with pytest.raises(AMQPConnectionError):
            await conn.channel()
        await conn.channel()

        assert listener.await_count == 2

    @patch("libs.events.rabbitmq.aio_pika.connect_robust", new_callable=AsyncMock)
    async def test_close(self, mock_connect):
        mock_connect.return_value.is_closed = False
        conn = RabbitMQConnection("amqp://localhost")
        await conn.channel()

        await conn.close()
        await conn.channel()

        mock_connect.return_value.close.assert_awaited_once()
        assert mock_connect.await_count == 2


class TestRabbitMQDispatcher:
    async def test_dispatch_publishes_event_successfully(self):
        channel = MagicMock()
        exchange = channel.get_exchange = AsyncMock()
        exchange.return_value.publish = AsyncMock()
        encoder = JsonEncoder()
        dispatcher = RabbitMQDispatcher(make_connection(channel), encoder, "test_exchange", timeout_seconds=3)
        event = RabbitSampleEvent("hello")

        await dispatcher.dispatch(event)

        channel.get_exchange.assert_awaited_once_with("test_exchange", ensure=False)
        publish = exchange.return_value.publish
        publish.assert_awaited_once()
        message = publish.call_args.args[0]
        assert message.body == encoder.encode(event).encode()
        assert message.delivery_mode == DeliveryMode.PERSISTENT
        assert publish.call_args.kwargs == {"routing_key": "test.rabbit_event", "mandatory": True, "timeout": 3}

    @pytest.mark.parametrize(
        "error",
        [
            DeliveryError(None, Basic.Nack(delivery_tag=1)),
            PublishError(
                MagicMock(delivery=Basic.Return(reply_code=312, reply_text="NO_ROUTE")),
                Basic.Return(reply_code=312, reply_text="NO_ROUTE"),
            ),
        ],
    )
    async def test_dispatch_raises_when_broker_rejects_the_event(self, error):
        channel = MagicMock()
        channel.get_exchange = AsyncMock()
        channel.get_exchange.return_value.publish = AsyncMock(side_effect=error)
        dispatcher = RabbitMQDispatcher(make_connection(channel), JsonEncoder(), "test_exchange")

        with pytest.raises(EventDispatchError, match='RabbitMQ rejected event "test.rabbit_event"'):
            await dispatcher.dispatch(RabbitSampleEvent("rejected"))

    @pytest.mark.parametrize(
        "error",
        [AMQPConnectionError("lost"), ChannelInvalidStateError("closed"), OSError("dns"), TimeoutError()],
    )
    async def test_dispatch_raises_on_connection_failures(self, error):
        channel = MagicMock()
        channel.get_exchange = AsyncMock()
        channel.get_exchange.return_value.publish = AsyncMock(side_effect=error)
        dispatcher = RabbitMQDispatcher(make_connection(channel), JsonEncoder(), "test_exchange")

        with pytest.raises(EventDispatchError, match='Failed to dispatch event "test.rabbit_event"'):
            await dispatcher.dispatch(RabbitSampleEvent("fail_event"))

    async def test_dispatch_raises_when_it_can_not_connect(self):
        connection = make_connection()
        connection.channel.side_effect = AMQPConnectionError("refused")
        dispatcher = RabbitMQDispatcher(connection, JsonEncoder(), "test_exchange")

        with pytest.raises(EventDispatchError, match='Failed to dispatch event "test.rabbit_event"'):
            await dispatcher.dispatch(RabbitSampleEvent("fail_event"))


class TestRabbitMQGracefulConsumer:
    def make_consumer(self, decoder: MagicMock, dispatcher: MagicMock | None = None) -> RabbitMQGracefulConsumer:
        return RabbitMQGracefulConsumer(make_connection(), "q", decoder, dispatcher or MagicMock(spec=Dispatcher))

    async def test_on_message_success_acks(self):
        event = RabbitSampleEvent("success")
        decoder = MagicMock()
        decoder.decode.return_value = event
        dispatcher = MagicMock(spec=Dispatcher)
        dispatcher.dispatch = AsyncMock()
        message = make_message(b"body")

        await self.make_consumer(decoder, dispatcher).on_message(message)

        decoder.decode.assert_called_once_with(b"body")
        dispatcher.dispatch.assert_awaited_once_with(event)
        message.ack.assert_awaited_once()
        message.nack.assert_not_awaited()

    async def test_on_message_decode_failure_nacks_without_requeue(self):
        decoder = MagicMock()
        decoder.decode.side_effect = EventDecodeError("corrupt json")
        dispatcher = MagicMock(spec=Dispatcher)
        dispatcher.dispatch = AsyncMock()
        message = make_message(b"invalid")

        await self.make_consumer(decoder, dispatcher).on_message(message)

        message.nack.assert_awaited_once_with(requeue=False)
        message.ack.assert_not_awaited()
        dispatcher.dispatch.assert_not_awaited()

    async def test_on_message_nacks_unmapped_events(self):
        decoder = MagicMock()
        decoder.decode.side_effect = UnmappedEventError("other_context.something.happened")
        message = make_message()

        await self.make_consumer(decoder).on_message(message)

        message.nack.assert_awaited_once_with(requeue=False)
        message.ack.assert_not_awaited()

    async def test_on_message_dispatch_failure_nacks_without_requeue(self):
        decoder = MagicMock()
        decoder.decode.return_value = RabbitSampleEvent("crash")
        dispatcher = MagicMock(spec=Dispatcher)
        dispatcher.dispatch = AsyncMock(side_effect=RuntimeError("handler crashed"))
        message = make_message()

        await self.make_consumer(decoder, dispatcher).on_message(message)

        message.nack.assert_awaited_once_with(requeue=False)
        message.ack.assert_not_awaited()

    async def test_on_message_does_not_crash_when_ack_fails(self):
        decoder = MagicMock()
        decoder.decode.return_value = RabbitSampleEvent("lost connection")
        dispatcher = MagicMock(spec=Dispatcher)
        dispatcher.dispatch = AsyncMock()
        message = make_message()
        message.ack.side_effect = ChannelInvalidStateError("closed")

        await self.make_consumer(decoder, dispatcher).on_message(message)

        message.ack.assert_awaited_once()

    async def test_start_consumes_until_stop_and_finishes_the_current_message(self):
        received = asyncio.Event()
        release = asyncio.Event()
        processed: list[str] = []

        class Iterator:
            def __init__(self) -> None:
                self.closed = asyncio.Event()
                self.close = AsyncMock(side_effect=self.closed.set)
                self.sent = False

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                await self.close()

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not self.sent:
                    self.sent = True
                    return make_message(b"first")
                await self.closed.wait()
                raise StopAsyncIteration

        iterator = Iterator()
        queue = MagicMock()
        queue.iterator.return_value = iterator
        channel = MagicMock()
        channel.set_qos = AsyncMock()
        channel.get_queue = AsyncMock(return_value=queue)
        connection = make_connection(channel)

        decoder = MagicMock()
        decoder.decode.return_value = RabbitSampleEvent("first")
        dispatcher = MagicMock(spec=Dispatcher)

        async def dispatch(event: RabbitSampleEvent) -> None:
            received.set()
            await release.wait()
            processed.append(event.data)

        dispatcher.dispatch = AsyncMock(side_effect=dispatch)
        consumer = RabbitMQGracefulConsumer(connection, "my_queue", decoder, dispatcher, prefetch_count=5)

        with patch.object(asyncio.get_running_loop(), "add_signal_handler") as add_signal_handler:
            task = asyncio.create_task(consumer.start())
            await received.wait()
            await consumer.stop()  # while the message is being processed
            release.set()
            await asyncio.wait_for(task, timeout=1)

        assert processed == ["first"]
        channel.set_qos.assert_awaited_once_with(prefetch_count=5)
        channel.get_queue.assert_awaited_once_with("my_queue")
        assert {call.args[0] for call in add_signal_handler.call_args_list} == {signal.SIGTERM, signal.SIGINT}
        connection.close.assert_awaited_once()

    async def test_stop_before_start_does_not_consume(self):
        iterator = MagicMock()
        iterator.__aenter__ = AsyncMock(return_value=iterator)
        iterator.__aexit__ = AsyncMock()
        queue = MagicMock()
        queue.iterator.return_value = iterator
        channel = MagicMock()
        channel.set_qos = AsyncMock()
        channel.get_queue = AsyncMock(return_value=queue)
        connection = make_connection(channel)
        consumer = RabbitMQGracefulConsumer(connection, "q", MagicMock(), MagicMock(spec=Dispatcher))

        await consumer.stop()
        await consumer.start()

        iterator.__aiter__.assert_not_called()
        connection.close.assert_awaited_once()
