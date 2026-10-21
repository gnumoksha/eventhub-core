#!/usr/bin/env python

"""Events consumer entrypoint"""

import asyncio

import sales.application as application_layer
import sales.domain.models as models_layer
from libs.events import load_events, load_listeners
from shared.infra.domain_events import consume_events

if __name__ == "__main__":
    load_events(models_layer)
    load_listeners(application_layer)

    print("Waiting for messages. To exit press CTRL+C")
    asyncio.run(consume_events("sales"))
    print("Application exited.")
