"""
Setup the infrastructure for the async domain events.
"""

import platform
from typing import Annotated, override

from fastapi import Depends
from libs.events import (
    Config,
    Dispatcher,
    JsonEncoder,
    RabbitMQConnection,
    RabbitMQDispatcher,
    SyncDispatcher,
)
from pika.adapters.blocking_connection import (
    BlockingChannel,
)
from shared.settings import settings


class DomainEventsConfig(Config):
    @override
    @property
    def exchange(self) -> str:
        return "events"

    @override
    @property
    def queue(self) -> str:
        return "events"

    @override
    @property
    def routing_key(self) -> str:
        return "eventhub.events.events"  # $app_name.$domain_name.events


domain_events_config = DomainEventsConfig()


def declare_events_topology(channel: BlockingChannel) -> None:
    """
    Declares the events queue along with its dead-letter exchange/queue.

    Messages that are nacked without requeue (decode/dispatch failures) are
    routed here instead of being discarded, so they can be inspected and,
    if needed, replayed.
    """

    # Setup Dead Letter (DLX)
    exchange_dlx_name = domain_events_config.exchange + "_dlx"
    queue_dlx_name = domain_events_config.queue + "_dlx"
    channel.exchange_declare(
        exchange=exchange_dlx_name,
        exchange_type="fanout",
        durable=True,
    )
    channel.queue_declare(
        queue=queue_dlx_name,
        durable=True,
        arguments={
            "x-queue-type": "quorum",
            # do not store many messages in memory to avoid running out of memory
            "x-max-in-memory-length": 100,
        },
    )
    channel.queue_bind(
        queue=queue_dlx_name,
        exchange=exchange_dlx_name,
        routing_key="eventhub.domainY.events",
    )

    # Setup main exchange and queue
    channel.exchange_declare(
        exchange=domain_events_config.exchange,
        # fanout: broadcasts all the messages it receives to all the queues it knows
        # others are: direct, topic, headers
        exchange_type="fanout",
        durable=True,
    )
    channel.queue_declare(
        queue=domain_events_config.queue,
        durable=True,
        arguments={
            "x-queue-type": "quorum",
            "x-dead-letter-exchange": domain_events_config.exchange,
            # do not store many messages in memory to avoid running out of memory
            "x-max-in-memory-length": 1000,
        },
    )
    channel.queue_bind(
        queue=domain_events_config.queue,
        exchange=domain_events_config.exchange,
        routing_key=domain_events_config.routing_key,
    )


def __get_sync_dispatcher() -> SyncDispatcher:
    return SyncDispatcher()


SyncDispatcherDep = Annotated[SyncDispatcher, Depends(__get_sync_dispatcher)]


_connection = RabbitMQConnection(
    settings.RABBITMQ_DSN,
    connection_name="dispatcher on " + platform.node(),
)
_connection.on_first_channel(declare_events_topology)


def get_queue_dispatcher() -> RabbitMQDispatcher:
    """Use it where FastAPI dependency injection is not available (e.g. Celery tasks)."""
    return RabbitMQDispatcher(_connection, JsonEncoder())


def __get_queue_dispatcher() -> RabbitMQDispatcher:
    return get_queue_dispatcher()


QueueDispatcherDep = Annotated[RabbitMQDispatcher, Depends(__get_queue_dispatcher)]

DispatcherDep = Annotated[Dispatcher, Depends(__get_queue_dispatcher)]
