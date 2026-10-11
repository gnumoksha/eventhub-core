# Notifications

Notifications bounded context (generic subdomain).

Sends transactional messages (e-mail, push, WhatsApp) in reaction to events from the other contexts: order confirmation, tickets, transfers, event postponement or cancellation, payouts. It has no business rules beyond templates and delivery preferences.

See [bounded_contexts.md](../../var/docs/bounded_contexts.md#notifications).
