# Payments

Payments bounded context (generic subdomain).

Talks to the payment gateway (PIX, credit card) behind an anti-corruption layer, so gateway statuses, webhooks and idempotency keys never leak into other contexts. It charges paid orders, issues refunds and reports chargebacks.

See [bounded_contexts.md](../../var/docs/bounded_contexts.md#payments).
