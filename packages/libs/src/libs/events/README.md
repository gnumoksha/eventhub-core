# Events

Library for domain events, synchronous listeners, JSON serialization, and RabbitMQ transport.

## RabbitMQ delivery behavior

`RabbitMQDispatcher` uses persistent messages and publisher confirms. A publish is
considered successful only after the broker confirms it; rejected or unroutable
messages raise `EventDispatchError`. Connection failures are retried once. If the
connection drops after the broker accepted a message but before the confirmation
reaches the publisher, the retry can create a duplicate. Event listeners must
therefore be idempotent.

`RabbitMQGracefulConsumer` acknowledges messages after all synchronous listeners
finish. Decode or listener failures are nacked without requeue. The queue must
have a dead-letter exchange configured if failed messages need to be inspected
or replayed. Configure SIGTERM/SIGINT handling by calling `start()` from the
process main thread.

`JsonDecoder` raises `EventDecodeError` for malformed event envelopes and
`UnmappedEventError` when the event name has not been registered. Load event
modules before consuming messages.
