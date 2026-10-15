# Events

Event Management bounded context (core subdomain).

Manages the event as a product: title, description, age rating, venue (physical or online) and period. It owns the event lifecycle (`draft → published → postponed → cancelled | finished`) and publishes `EventPublished`, `EventPostponed`, `EventCancelled` and `EventFinished`. Ticket types, batches and prices do not live here; they belong to Sales.

See [bounded_contexts.md](../../var/docs/bounded_contexts.md#event-management).
