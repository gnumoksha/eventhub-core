import asyncio
import signal
from collections.abc import Awaitable, Callable
from typing import override

import aio_pika
from aio_pika import DeliveryMode, Message
from aio_pika.abc import (
    AbstractChannel,
    AbstractIncomingMessage,
    AbstractQueueIterator,
    AbstractRobustConnection,
)
from aio_pika.exceptions import AMQPError, ChannelInvalidStateError, DeliveryError

from .consumer import Consumer
from .dispatcher import Dispatcher, EventDispatchError
from .encoding import Decoder, Encoder, UnmappedEventError
from .event import PublishableEvent
from .logger import logger

ChannelListener = Callable[[AbstractChannel], Awaitable[None]]


class RabbitMQConnection:
    """
    Lazily opens a robust connection and a single channel.

    The robust connection reconnects by itself and restores the exchanges, queues,
    bindings and consumers declared on its channels.
    """

    def __init__(self, amqp_url: str, *, connection_name: str | None = None):
        self._amqp_url = amqp_url
        self._name = connection_name
        self._listeners_on_channel: list[ChannelListener] = []
        self._listeners_called = False
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractChannel | None = None
        self._lock = asyncio.Lock()

    def on_first_channel(self, listener: ChannelListener) -> None:
        """Add a listener for the first time we get a Channel (e.g. to declare the topology)."""
        self._listeners_on_channel.append(listener)

    async def channel(self) -> AbstractChannel:
        async with self._lock:
            if self._channel is None or self._channel.is_closed:
                if self._connection is None or self._connection.is_closed:
                    self._connection = await aio_pika.connect_robust(
                        self._amqp_url,
                        client_properties={"connection_name": self._name} if self._name else None,
                    )

                # Publisher confirms make publish() wait for the broker to accept the message, and
                # on_return_raises makes it raise when the message can not be routed to any queue.
                channel = await self._connection.channel(publisher_confirms=True, on_return_raises=True)
                if not self._listeners_called:
                    for listener in self._listeners_on_channel:
                        await listener(channel)
                    self._listeners_called = True

                self._channel = channel

            return self._channel

    async def close(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None
        self._channel = None


class RabbitMQDispatcher(Dispatcher):
    def __init__(
        self,
        connection: RabbitMQConnection,
        encoder: Encoder,
        exchange: str,
        *,
        timeout_seconds: float = 10,
    ) -> None:
        """
        Publishes every event to the exchange, using the event name as the routing key.

        Args:
          exchange: A topic or direct exchange; the queues bind the names of the events they listen to.
          timeout_seconds: Bounds how long a publish can wait for the broker confirmation
            (e.g. during a resource alarm) instead of hanging indefinitely.
        """
        self._connection = connection
        self._encoder = encoder
        self._exchange = exchange
        self._timeout_seconds = timeout_seconds

    @override
    async def dispatch(self, event: PublishableEvent) -> None:
        body = self._encoder.encode(event)
        message = Message(
            body.encode() if isinstance(body, str) else body,
            # We cannot afford to lose any event, so we already have declared the queue
            # as "durable" and here messages are sent with delivery mode "persistent".
            # "persistent" means RabbitMQ will store the message on disk.
            delivery_mode=DeliveryMode.PERSISTENT,
        )

        try:
            channel = await self._connection.channel()
            exchange = await channel.get_exchange(self._exchange, ensure=False)
            await exchange.publish(
                message,
                # The meaning of a binding key depends on the exchange type.
                #  - fanout = simply ignored its value.
                #  - direct = a message goes to the queues whose binding key exactly matches the routing key of the message.
                #  - topic = a message sent with a particular routing key will be delivered to all the queues that are bound
                #    with a matching binding key. However there are two important special cases for binding keys:
                #    * (star) can substitute for exactly one word. When a queue is bound with # (hash) binding key
                #      it will receive all the messages, regardless of the routing key - like in fanout exchange.
                #    # (hash) can substitute for zero or more words. When special characters * (star) and # (hash) aren't
                #      used in bindings, the topic exchange will behave just like a direct one.
                routing_key=event.name(),
                mandatory=True,
                timeout=self._timeout_seconds,
            )
        except DeliveryError as exc:
            # The broker nacked the message or could not route it (PublishError is a subclass). An event
            # that no queue listens to is not an error if the exchange has an alternate exchange.
            raise EventDispatchError(f'RabbitMQ rejected event "{event.NAME}"') from exc
        except (AMQPError, ChannelInvalidStateError, OSError) as exc:
            # OSError includes TimeoutError. The robust connection reconnects in the background; the caller retries later.
            raise EventDispatchError(f'Failed to dispatch event "{event.NAME}"') from exc


class RabbitMQGracefulConsumer(Consumer):
    """Events consumer that gets messages from RabbitMQ and handles SIGTERM/SIGINT"""

    def __init__(
        self,
        connection: RabbitMQConnection,
        queue: str,
        decoder: Decoder,
        dispatcher: Dispatcher,
        *,
        prefetch_count: int = 1,
    ):
        self._connection = connection
        self._queue = queue
        self._decoder = decoder
        self._dispatcher = dispatcher
        self._prefetch_count = prefetch_count
        self._messages: AbstractQueueIterator | None = None
        self._stopping = False
        self._stop_task: asyncio.Task[None] | None = None

    async def on_message(self, message: AbstractIncomingMessage) -> None:
        try:
            event = self._decoder.decode(message.body)
        except UnmappedEventError:
            # the message explains the causes: the event class was not loaded or the queue has an obsolete binding
            logger.exception("Failed to decode event delivery %s", message.delivery_tag)
            await self._settle(message, ack=False)
            return
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to decode event delivery %s (body size: %d bytes)",
                message.delivery_tag,
                len(message.body),
            )
            await self._settle(message, ack=False)
            return

        try:
            logger.debug(
                'Event "%s" was received from the queue and it will be dispatched',
                event.NAME,
            )

            await self._dispatcher.dispatch(event)
        except Exception:  # noqa: BLE001
            logger.exception('Failed to process event "%s"', event.NAME)
            await self._settle(message, ack=False)
            return

        # Acknowledge message after processing
        await self._settle(message, ack=True)

    async def _settle(self, message: AbstractIncomingMessage, *, ack: bool) -> None:
        """Acks the message, or nacks it without requeue so it goes to the dead-letter queue."""
        try:
            if ack:
                await message.ack()
            else:
                await message.nack(requeue=False)
        except AMQPError, ChannelInvalidStateError, OSError:
            # The connection was lost: the broker redelivers the message after the robust connection
            # reconnects (listeners are idempotent). Crashing here would stop the other consumers too.
            logger.exception("Could not settle event delivery %s", message.delivery_tag)

    def _on_signal(self, signum: int) -> None:
        logger.info("Received shutdown signal %s; stopping consumer", signum)
        self._stop_task = asyncio.create_task(self.stop())

    @override
    async def start(self) -> None:
        """Consumes messages until stop() is called or SIGTERM/SIGINT is received."""
        loop = asyncio.get_running_loop()
        signals = (signal.SIGTERM, signal.SIGINT)
        for signum in signals:
            loop.add_signal_handler(signum, self._on_signal, signum)

        try:
            channel = await self._connection.channel()
            await channel.set_qos(prefetch_count=self._prefetch_count)
            queue = await channel.get_queue(self._queue)
            async with queue.iterator() as messages:
                self._messages = messages
                if self._stopping:
                    return
                async for message in messages:
                    await self.on_message(message)
        finally:
            for signum in signals:
                loop.remove_signal_handler(signum)
            await self._connection.close()

    @override
    async def stop(self) -> None:
        """
        Stops receiving new messages. The message being processed is finished and acknowledged;
        the prefetched ones are requeued.
        """
        self._stopping = True
        if self._messages is not None:
            await self._messages.close()
