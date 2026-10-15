# Roadmap

The bounded contexts are described in [bounded_contexts.md](bounded_contexts.md).

## MVP: end-to-end ticket sales

Vertical slices, in order:

0. **Domain event infrastructure:** nested payload in `SerializableDict` and fix the dead letter of the `events` queue.
1. **identity + organizers:** accounts, organizations, members with roles, KYC and payout account.
2. **events:** create, edit, publish, postpone and cancel events (single period, no sessions).
3. **sales:** ticket offers, batches (*lotes*), reservations with Redis + TTL, orders with mandatory attendee data, per-CPF limits, free orders confirmed without payment.
4. **payments:** gateway in sandbox (PIX / card) behind an ACL, idempotent webhooks, refunds.
5. **ticketing + checkin:** named ticket issuance with signed QR, ticket transfer, online check-in.
6. **finance:** fee policy, double-entry ledger, manual / semi-automatic payouts released N days after the event.
7. **notifications:** transactional e-mails (order, tickets, transfer, postponement, cancellation).

## After the MVP

- Unit of Work
- Offline check-in
- Automatic payouts and chargeback handling
- Coupons, affiliates and half-price tickets (*meia-entrada*)
- Reporting: organizer sales dashboard
- Fiscal: service invoices on platform fees
- Seating: seat maps and seat-level reservations
- Waiting room for high-demand events

## Semantic search

Examples:

- horror movie night

## Similar events

- new microservice?
- https://github.com/meilisearch/meilisearch
- Postgres FTS
- Elasticsearch