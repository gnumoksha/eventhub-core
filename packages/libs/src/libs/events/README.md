# Events

Library for domain events, async listeners, JSON serialization, and RabbitMQ transport (aio-pika).

## Event names

The event name is the routing key and the binding key in the broker, so it must be lowercase
words (`a-z`, `0-9`, `_`) separated by dots, e.g. `eventhub.sales.order.placed`; wildcards
(`*`, `#`) are rejected. `listened_event_names()` returns the names of the events that have
listeners in the process, so a consumer binds its queue only to them.

## Listeners

Listeners are `async def` functions registered with `@listener(EventClass)`. The decorator
raises `TypeError` for sync functions: they would be called without being awaited, so their
work would silently never happen. `LocalDispatcher` calls the listeners registered in the
process one after the other; the first failure stops the remaining listeners and the whole
event is retried, so listeners must be idempotent.

## RabbitMQ delivery behavior

`RabbitMQConnection` uses a robust aio-pika connection: it reconnects in the background and
restores the declared exchanges, queues, bindings and consumers.

`RabbitMQDispatcher` publishes every event to one exchange, using the event name as the routing
key, with persistent messages and publisher confirms. A publish is
considered successful only after the broker confirms it; rejected or unroutable
messages raise `EventDispatchError`, as do connection failures and timeouts. It does not
retry: the caller (e.g. the outbox relay) retries later. If the connection drops after the
broker accepted a message but before the confirmation reaches the publisher, the retry can
create a duplicate. Event listeners must therefore be idempotent.

`RabbitMQGracefulConsumer` acknowledges messages after all listeners finish. Decode or
listener failures are nacked without requeue. The queue must have a dead-letter exchange
configured if failed messages need to be inspected or replayed. A queue should receive only
the events it has listeners for, so an event whose class is not loaded (`UnmappedEventError`)
is always an error; besides a missing `load_events()`, it can be an obsolete binding, because
bindings are durable and are not removed with the listener: remove it manually. A known event
without listeners is acknowledged with a warning for the same reason. On SIGTERM/SIGINT it stops consuming, finishes
the message being processed and requeues the prefetched ones; call `start()` from the
process main thread.

`JsonDecoder` raises `EventDecodeError` for malformed event envelopes and
`UnmappedEventError` when the event name has not been registered. Load event
modules before consuming messages.
