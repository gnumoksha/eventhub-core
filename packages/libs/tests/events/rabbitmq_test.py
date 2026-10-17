from typing import Self, override
from unittest.mock import MagicMock, patch

import pytest
from libs.events.dispatcher import EventDispatchError, SyncDispatcher
from libs.events.encoding import JsonEncoder
from libs.events.event import Config, Metadata, PublishableEvent, SerializableDict
from libs.events.rabbitmq import (
    RabbitMQConnection,
    RabbitMQDispatcher,
    RabbitMQGracefulConsumer,
)
from pika import DeliveryMode
from pika.exceptions import AMQPConnectionError


class RabbitConfig(Config):
    @property
    @override
    def exchange(self) -> str:
        return "test_exchange"

    @property
    @override
    def queue(self) -> str:
        return "test_queue"

    @property
    @override
    def routing_key(self) -> str:
        return "test.route"


class RabbitSampleEvent(PublishableEvent, name="test:rabbit_event"):
    def __init__(self, data: str, metadata: Metadata | None = None) -> None:
        super().__init__(RabbitConfig(), metadata)
        self.data = data

    @override
    def to_dict(self) -> SerializableDict:
        return {"data": self.data}

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(str(payload["data"]), metadata)


class TestRabbitMQConnection:
    @patch("libs.events.rabbitmq.pika.BlockingConnection")
    def test_connection_creation_with_params(self, mock_blocking_conn):
        conn = RabbitMQConnection(
            "amqp://guest:guest@localhost:5672/",
            connection_name="my_worker",
            blocked_timeout_seconds=15,
        )

        res = conn.connection()
        assert res == mock_blocking_conn.return_value
        mock_blocking_conn.assert_called_once()
        params = mock_blocking_conn.call_args[0][0]
        assert params.blocked_connection_timeout == 15
        assert params.client_properties["connection_name"] == "my_worker"

    @patch("libs.events.rabbitmq.pika.BlockingConnection")
    def test_connection_cached_until_reset(self, mock_blocking_conn):
        conn = RabbitMQConnection("amqp://localhost")
        c1 = conn.connection()
        c2 = conn.connection()
        assert c1 == c2
        assert mock_blocking_conn.call_count == 1

        conn.reset_connection()
        _ = conn.connection()
        assert mock_blocking_conn.call_count == 2

    @patch("libs.events.rabbitmq.pika.BlockingConnection")
    def test_channel_listener_called_on_first_channel(self, mock_blocking_conn):
        mock_conn = MagicMock()
        mock_channel = MagicMock()
        mock_channel.is_open = True
        mock_conn.channel.return_value = mock_channel
        mock_blocking_conn.return_value = mock_conn

        conn = RabbitMQConnection("amqp://localhost")
        listener_called = False

        def my_listener(ch):
            nonlocal listener_called
            listener_called = True
            assert ch == mock_channel

        conn.on_first_channel(my_listener)
        ch = conn.channel()

        assert ch == mock_channel
        assert listener_called

    @patch("libs.events.rabbitmq.pika.BlockingConnection")
    def test_reset_channel_does_not_call_listeners_again(self, mock_blocking_conn):
        mock_conn = MagicMock()
        mock_ch1 = MagicMock(is_open=True)
        mock_ch2 = MagicMock(is_open=True)
        mock_conn.channel.side_effect = [mock_ch1, mock_ch2]
        mock_blocking_conn.return_value = mock_conn

        conn = RabbitMQConnection("amqp://localhost")
        listener_call_count = 0

        def my_listener(ch):
            nonlocal listener_call_count
            listener_call_count += 1

        conn.on_first_channel(my_listener)
        assert conn.channel() == mock_ch1
        assert listener_call_count == 1

        conn.reset_channel()
        assert conn.channel() == mock_ch2
        assert listener_call_count == 1  # Not called again after reset


class TestRabbitMQDispatcher:
    def test_dispatch_publishes_event_successfully(self):
        mock_conn = MagicMock()
        mock_channel = MagicMock()
        mock_conn.channel.return_value = mock_channel

        encoder = JsonEncoder()
        dispatcher = RabbitMQDispatcher(mock_conn, encoder)
        event = RabbitSampleEvent("hello")

        dispatcher.dispatch(event)

        mock_channel.basic_publish.assert_called_once()
        kwargs = mock_channel.basic_publish.call_args.kwargs
        assert kwargs["exchange"] == "test_exchange"
        assert kwargs["routing_key"] == "test.route"
        assert kwargs["body"] == encoder.encode(event)
        assert kwargs["properties"].delivery_mode == DeliveryMode.Persistent.value

    def test_dispatch_retries_on_connection_error(self):
        mock_conn = MagicMock()
        mock_channel = MagicMock()
        mock_conn.channel.return_value = mock_channel

        # First call fails, second succeeds
        mock_channel.basic_publish.side_effect = [AMQPConnectionError("lost"), None]

        dispatcher = RabbitMQDispatcher(mock_conn, JsonEncoder())
        event = RabbitSampleEvent("retry_me")

        dispatcher.dispatch(event)

        assert mock_channel.basic_publish.call_count == 2
        mock_conn.reset_channel.assert_called_once()

    def test_dispatch_raises_event_dispatch_error_if_retry_fails(self):
        mock_conn = MagicMock()
        mock_channel = MagicMock()
        mock_conn.channel.return_value = mock_channel

        # Both attempts fail
        mock_channel.basic_publish.side_effect = [
            AMQPConnectionError("fail 1"),
            OSError("fail 2"),
        ]

        dispatcher = RabbitMQDispatcher(mock_conn, JsonEncoder())
        event = RabbitSampleEvent("fail_event")

        with pytest.raises(EventDispatchError, match='Failed to dispatch event "test:rabbit_event" after reconnecting'):
            dispatcher.dispatch(event)

        assert mock_channel.basic_publish.call_count == 2
        mock_conn.reset_channel.assert_called_once()


class TestRabbitMQGracefulConsumer:
    @patch("libs.events.rabbitmq.signal.signal")
    def test_consumer_initialization(self, mock_signal):
        mock_conn = MagicMock()
        mock_channel = MagicMock()
        mock_conn.channel.return_value = mock_channel
        mock_decoder = MagicMock()
        mock_dispatcher = MagicMock(spec=SyncDispatcher)

        consumer = RabbitMQGracefulConsumer(
            connection=mock_conn,
            queue="my_queue",
            decoder=mock_decoder,
            dispatcher=mock_dispatcher,
        )

        mock_channel.basic_qos.assert_called_once_with(prefetch_count=1)
        mock_channel.basic_consume.assert_called_once_with(
            queue="my_queue",
            on_message_callback=consumer.on_message,
            auto_ack=False,
        )
        mock_signal.assert_not_called()

    @patch("libs.events.rabbitmq.signal.signal")
    def test_on_message_success_acks(self, _mock_signal):
        mock_conn = MagicMock()
        mock_decoder = MagicMock()
        mock_dispatcher = MagicMock(spec=SyncDispatcher)
        mock_ch = MagicMock()
        mock_method = MagicMock(delivery_tag=123)
        mock_props = MagicMock()

        event = RabbitSampleEvent("success")
        mock_decoder.decode.return_value = event

        consumer = RabbitMQGracefulConsumer(mock_conn, "q", mock_decoder, mock_dispatcher)
        consumer.on_message(mock_ch, mock_method, mock_props, b"body")

        mock_decoder.decode.assert_called_once_with(b"body")
        mock_dispatcher.dispatch.assert_called_once_with(event)
        mock_ch.basic_ack.assert_called_once_with(delivery_tag=123)
        mock_ch.basic_nack.assert_not_called()

    @patch("libs.events.rabbitmq.signal.signal")
    def test_on_message_decode_failure_nacks_without_requeue(self, _mock_signal):
        mock_conn = MagicMock()
        mock_decoder = MagicMock()
        mock_decoder.decode.side_effect = ValueError("corrupt json")
        mock_dispatcher = MagicMock(spec=SyncDispatcher)
        mock_ch = MagicMock()
        mock_method = MagicMock(delivery_tag=456)
        mock_props = MagicMock()

        consumer = RabbitMQGracefulConsumer(mock_conn, "q", mock_decoder, mock_dispatcher)
        consumer.on_message(mock_ch, mock_method, mock_props, b"invalid")

        mock_ch.basic_nack.assert_called_once_with(delivery_tag=456, requeue=False)
        mock_ch.basic_ack.assert_not_called()
        mock_dispatcher.dispatch.assert_not_called()

    @patch("libs.events.rabbitmq.signal.signal")
    def test_on_message_dispatch_failure_nacks_without_requeue(self, _mock_signal):
        mock_conn = MagicMock()
        mock_decoder = MagicMock()
        mock_dispatcher = MagicMock(spec=SyncDispatcher)
        mock_dispatcher.dispatch.side_effect = RuntimeError("handler crashed")
        mock_ch = MagicMock()
        mock_method = MagicMock(delivery_tag=789)
        mock_props = MagicMock()

        event = RabbitSampleEvent("crash")
        mock_decoder.decode.return_value = event

        consumer = RabbitMQGracefulConsumer(mock_conn, "q", mock_decoder, mock_dispatcher)
        consumer.on_message(mock_ch, mock_method, mock_props, b"valid")

        mock_ch.basic_nack.assert_called_once_with(delivery_tag=789, requeue=False)
        mock_ch.basic_ack.assert_not_called()

    @patch("libs.events.rabbitmq.signal.signal")
    def test_start_and_stop(self, _mock_signal):
        mock_conn = MagicMock()
        mock_channel = MagicMock(is_open=True)
        mock_pika_conn = MagicMock(is_open=True)
        mock_conn.channel.return_value = mock_channel
        mock_conn.connection.return_value = mock_pika_conn
        mock_conn.close.side_effect = lambda: setattr(mock_channel, "is_open", False)

        consumer = RabbitMQGracefulConsumer(mock_conn, "q", MagicMock(), MagicMock(spec=SyncDispatcher))

        consumer.start()
        mock_channel.start_consuming.assert_called_once()
        assert _mock_signal.call_count == 2

        mock_channel.stop_consuming.assert_called_once()
        mock_conn.close.assert_called_once()
