import signal
from collections.abc import Callable
from types import FrameType
from typing import override

import pika
from pika import BlockingConnection, DeliveryMode
from pika.adapters.blocking_connection import (
    BlockingChannel,
)
from pika.exceptions import AMQPConnectionError
from pika.spec import Basic, BasicProperties

from .consumer import Consumer
from .dispatcher import Dispatcher, EventDispatchError, SyncDispatcher
from .encoding import Decoder, Encoder
from .event import PublishableEvent
from .logger import logger

ChannelListener = Callable[[BlockingChannel], None]


# TODO create an async connection for the event dispatcher
class RabbitMQConnection:
    def __init__(
        self,
        amqp_url: str,
        *,
        connection_name: str | None = None,
        blocked_timeout_seconds: int = 10,
    ):
        """
        Args:
          blocked_timeout_seconds: Bounds how long a publish can block if the
            broker connection stalls (e.g. a resource alarm) instead of
            hanging indefinitely.
        """
        self._amqp_url = amqp_url
        self._name = connection_name
        self._blocked_timeout_seconds = blocked_timeout_seconds
        self._listeners_on_channel: list[ChannelListener] = []
        self._connection: BlockingChannel | None = None
        self._channel: BlockingChannel | None = None
        self._channel_reset = False

    def on_first_channel(self, listener: ChannelListener) -> None:
        """Add a listener for the first time we get a Channel."""
        self._listeners_on_channel.append(listener)

    def connection(self) -> BlockingConnection:
        if not self._connection:
            params = pika.URLParameters(self._amqp_url)
            params.blocked_connection_timeout = self._blocked_timeout_seconds

            if params.client_properties is None:
                params.client_properties = {}
            if self._name:
                params.client_properties["connection_name"] = self._name

            self._connection = pika.BlockingConnection(params)

        return self._connection

    def reset_connection(self) -> None:
        self._connection = None

    def channel(self) -> BlockingChannel:
        if not self._channel or not self._channel.is_open:
            channel = self.connection().channel()
            if not self._channel_reset:
                for listener in self._listeners_on_channel:
                    listener(channel)

            self._channel = channel

        return self._channel

    def reset_channel(self) -> None:
        self._channel = None
        self._channel_reset = True


class RabbitMQDispatcher(Dispatcher):
    def __init__(
        self,
        connection: RabbitMQConnection,
        encoder: Encoder,
    ) -> None:
        self._connection = connection
        self._encoder = encoder

    @override
    def dispatch(self, event: PublishableEvent) -> None:
        try:
            self._publish(event)
            return
        except AMQPConnectionError, OSError:
            # pika does not always wrap socket failures (e.g. DNS resolution) in AMQPConnectionError
            logger.exception(
                'Lost connection to RabbitMQ while dispatching event "%s", reconnecting',
                event.NAME,
            )
            self._connection.reset_channel()

        try:
            self._publish(event)
        except (AMQPConnectionError, OSError) as exc:
            raise EventDispatchError(f'Failed to dispatch event "{event.NAME}" after reconnecting') from exc

    def _publish(self, event: PublishableEvent) -> None:
        self._connection.channel().basic_publish(
            exchange=event.config.exchange,
            # The meaning of a binding key depends on the exchange type.
            #  - fanout = simply ignored its value.
            #  - direct = a message goes to the queues whose binding key exactly matches the routing key of the message.
            #  - topic = a message sent with a particular routing key will be delivered to all the queues that are bound
            #    with a matching binding key. However there are two important special cases for binding keys:
            #    * (star) can substitute for exactly one word. When a queue is bound with # (hash) binding key
            #      it will receive all the messages, regardless of the routing key - like in fanout exchange.
            #    # (hash) can substitute for zero or more words. When special characters * (star) and # (hash) aren't
            #      used in bindings, the topic exchange will behave just like a direct one.
            routing_key=event.config.routing_key,
            body=self._encoder.encode(event),  # ty:ignore[invalid-argument-type]
            properties=pika.BasicProperties(
                # We cannot afford to lose any event, so we already have declared the queue
                # as "durable" and here messages are sent with delivery mode "persistent".
                # "persistent" means RabbitMQ will store the message on disk.
                delivery_mode=DeliveryMode.Persistent,
            ),
        )


class RabbitMQGracefulConsumer(Consumer):
    """Events consumer that gets messages from RabbitMQ and handles SIGTERM/SIGINT"""

    def __init__(
        self,
        connection: RabbitMQConnection,
        queue: str,
        decoder: Decoder,
        dispatcher: SyncDispatcher,
    ):
        self._connection = connection
        self._decoder = decoder
        self._dispatcher = dispatcher
        self._connection = connection

        self._channel = self._connection.channel()
        self._channel.basic_qos(prefetch_count=1)
        self._channel.basic_consume(
            queue=queue,
            on_message_callback=self.on_message,
            auto_ack=False,
        )

        # Register signals for container stop (SIGTERM) and ctrl-c (SIGINT)
        signal.signal(signal.SIGTERM, self.exit_gracefully)
        signal.signal(signal.SIGINT, self.exit_gracefully)

    def on_message(
        self,
        ch: BlockingChannel,
        method: Basic.Deliver,
        properties: BasicProperties,  # noqa: ARG002
        body: bytes,
    ) -> None:
        try:
            event = self._decoder.decode(body)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to decode the event. Body: %s", body)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)  # ty:ignore[invalid-argument-type]
            return

        try:
            logger.debug(
                'Event "%s" was received from the queue and it will be dispatched',
                event.NAME,
            )

            self._dispatcher.dispatch(event)
        except Exception:  # noqa: BLE001
            logger.exception('Failed to process event "%s"', event.NAME)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)  # ty:ignore[invalid-argument-type]
            return

        # Acknowledge message after processing
        ch.basic_ack(delivery_tag=method.delivery_tag)  # ty:ignore[invalid-argument-type]

    def exit_gracefully(self, signum: int, frame: FrameType | None) -> None:  # noqa: ARG002
        print("Received shutdown signal, stopping consumer...")  # noqa: T201
        # Use add_callback_threadsafe if breaking from another thread,
        # or stop consuming directly on the blocking connection
        self._connection.connection().add_callback_threadsafe(self.stop)

    @override
    def start(self) -> None:
        self._channel.start_consuming()

    @override
    def stop(self) -> None:
        if self._connection.channel().is_open:
            self._channel.stop_consuming()

        if self._connection.connection().is_open:
            self._connection.connection().close()
