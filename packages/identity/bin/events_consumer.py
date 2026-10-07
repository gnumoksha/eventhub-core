#!/usr/bin/env python

"""Events consumer entrypoint"""

import platform

import identity.application as application_layer
import identity.domain.models as models_layer
from libs.events import (
    JsonDecoder,
    RabbitMQConnection,
    RabbitMQGracefulConsumer,
    SyncDispatcher,
    load_events,
    load_listeners,
)
from shared.infra.domain_events import declare_events_topology, domain_events_config
from shared.settings import settings

if __name__ == "__main__":
    load_events(models_layer)
    load_listeners(application_layer)

    connection = RabbitMQConnection(
        settings.RABBITMQ_DSN,
        connection_name="events consumer on " + platform.node(),
    )
    connection.on_first_channel(declare_events_topology)

    consumer = RabbitMQGracefulConsumer(
        connection,
        domain_events_config.queue,
        JsonDecoder(),
        SyncDispatcher(),
    )

    print("Waiting for messages. To exit press CTRL+C")
    consumer.start()
    print("Application exited.")
