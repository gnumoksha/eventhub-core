# Sales

Sales bounded context (core subdomain).

Covers everything between "I want to buy" and "the order is paid": ticket offers and their batches (*lotes*), inventory, temporary reservations with a TTL, and orders with the mandatory attendee data of each ticket. It guarantees that tickets are never oversold and enforces per-order and per-CPF limits. Free orders (total zero) are confirmed without going through Payments.

See [bounded_contexts.md](../../var/docs/bounded_contexts.md#sales).
