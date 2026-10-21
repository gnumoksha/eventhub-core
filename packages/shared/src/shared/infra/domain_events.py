"""
Setup the infrastructure for the async domain events.

Topology:
 - The relay publishes every event to the "events" topic exchange, using the
   event name as the routing key (e.g. "eventhub.identity.account.verification_requested").
 - Each context has its own queue ("<context>.events") with one binding per event it has
   listeners for, so it receives only those events. The bindings come from the listeners
   loaded in the consumer process.
 - Each context queue has its own dead-letter exchange and queue ("<context>.events.dlx"
   and "<context>.events.dlq") for the messages that failed.
 - Events that no queue listens to go to the alternate exchange and its queue
   ("events.unrouted"), so they are visible instead of making the publish fail.

Bindings are durable: removing a listener does not remove its binding. Remove obsolete
bindings manually (see UnmappedEventError).
"""

import platform
from typing import Annotated

from aio_pika import ExchangeType
from aio_pika.abc import AbstractChannel, AbstractExchange, AbstractQueue
from fastapi import Depends
from libs.events import (
    Dispatcher,
    JsonDecoder,
    JsonEncoder,
    LocalDispatcher,
    RabbitMQConnection,
    RabbitMQDispatcher,
    RabbitMQGracefulConsumer,
    listened_event_names,
)
from shared.settings import settings

EXCHANGE = "events"
_UNROUTED = f"{EXCHANGE}.unrouted"
_UNROUTED_TTL_MILLISECONDS = 7 * 24 * 60 * 60 * 1000
_UNROUTED_MAX_LENGTH = 100_000


async def __declare_events_exchange(channel: AbstractChannel) -> AbstractExchange:
    """
    Declares the exchange the events are published to, along with its alternate exchange/queue.

    The publisher and the consumers declare it with the same arguments, otherwise RabbitMQ refuses
    the declaration (PRECONDITION_FAILED).
    """
    # Setup the alternate exchange: it receives the events that do not match any binding
    unrouted_exchange = await channel.declare_exchange(_UNROUTED, ExchangeType.FANOUT, durable=True)
    unrouted_queue = await channel.declare_queue(
        _UNROUTED,
        durable=True,
        arguments={
            "x-queue-type": "quorum",
            # nobody consumes it: it only shows which events are not listened to, so it must not grow forever
            "x-message-ttl": _UNROUTED_TTL_MILLISECONDS,
            "x-max-length": _UNROUTED_MAX_LENGTH,
        },
    )
    await unrouted_queue.bind(unrouted_exchange)

    return await channel.declare_exchange(
        EXCHANGE,
        # topic: a message goes to the queues whose binding key matches its routing key (the event name)
        ExchangeType.TOPIC,
        durable=True,
        arguments={"alternate-exchange": _UNROUTED},
    )


def __context_queue_name(context: str) -> str:
    return f"{context}.events"


async def __declare_context_queue(channel: AbstractChannel, context: str) -> AbstractQueue:
    """
    Declares the context's events queue along with its dead-letter exchange/queue, and binds
    the queue to the events that have listeners loaded in this process.

    Messages that are nacked without requeue (decode/dispatch failures) are
    routed to the dead-letter queue instead of being discarded, so they can be
    inspected and, if needed, replayed.
    """
    queue_name = __context_queue_name(context)

    # Setup Dead Letter Exchange (DLX)
    dlx = await channel.declare_exchange(
        f"{queue_name}.dlx",
        ExchangeType.FANOUT,
        durable=True,
    )
    dlq = await channel.declare_queue(
        f"{queue_name}.dlq",
        durable=True,
        arguments={
            "x-queue-type": "quorum",
            # do not store many messages in memory to avoid running out of memory
            "x-max-in-memory-length": 100,
        },
    )
    await dlq.bind(dlx)

    # Setup main exchange and queue
    exchange = await __declare_events_exchange(channel)
    queue = await channel.declare_queue(
        queue_name,
        durable=True,
        arguments={
            "x-queue-type": "quorum",
            "x-dead-letter-exchange": dlx.name,
            # do not store many messages in memory to avoid running out of memory
            "x-max-in-memory-length": 1000,
        },
    )
    for event_name in listened_event_names():
        await queue.bind(exchange, routing_key=event_name)
    return queue


async def consume_events(context: str) -> None:
    """
    Consumes the context's queue, calling the listeners loaded in this process.

    Please, note that you need to load the events and the listeners before calling
    this function.
    """
    connection = RabbitMQConnection(
        settings.RABBITMQ_DSN,
        connection_name=f"{context} events consumer on {platform.node()}",
    )

    async def declare_topology(channel: AbstractChannel) -> None:
        await __declare_context_queue(channel, context)

    connection.on_first_channel(declare_topology)

    consumer = RabbitMQGracefulConsumer(
        connection,
        __context_queue_name(context),
        JsonDecoder(),
        LocalDispatcher(),
    )
    await consumer.start()


_connection = RabbitMQConnection(
    settings.RABBITMQ_DSN,
    connection_name="dispatcher on " + platform.node(),
)


async def __declare_exchange(channel: AbstractChannel) -> None:
    await __declare_events_exchange(channel)


_connection.on_first_channel(__declare_exchange)


async def close_dispatcher_connection() -> None:
    await _connection.close()


def __get_queue_dispatcher() -> RabbitMQDispatcher:
    return RabbitMQDispatcher(_connection, JsonEncoder(), EXCHANGE)


QueueDispatcherDep = Annotated[RabbitMQDispatcher, Depends(__get_queue_dispatcher)]
