# Bounded Contexts

Domain model for an event management and ticketing platform (similar to Sympla). The roadmap that sequences this work lives in [roadmap.md](roadmap.md).

## Product decisions that shape the model

| Decision | Consequence |
|---|---|
| Free events use the same flow with price zero | No separate "registration" (*inscrição*) flow. A zero-total `Order` is confirmed without going through Payments. |
| Tickets are nominal (named) and the attendee data is mandatory | Every order item carries attendee data (name, CPF, e-mail). Tickets are issued to a named holder. |
| Money flows through the platform | The platform holds the funds and pays organizers out (*repasse*). Finance (ledger + payouts) is part of the MVP. Organizer verification (KYC) is required to sell paid tickets. |
| Assigned seating will exist, but not in the MVP | Sales hides inventory behind an `Allocation` abstraction so that a future `Seating` context can plug in. |
| No recurring events | An `Event` has a single period (`start_at` / `end_at`, possibly spanning several days). There is no `Session` entity. |

## Subdomains

| Type | Subdomain | Why |
|---|---|---|
| **Core** | Event Management | How organizers create, configure and publish events |
| **Core** | Sales | Ticket batches (*lotes*), inventory, reservations, orders. Hardest rules: overselling, concurrency, per-CPF limits |
| **Core** | Ticketing | The ticket as a right of entry: named holder, transfer, invalidation |
| **Core** | Check-in | Gate validation, anti-fraud, offline operation (later) |
| **Supporting** | Organizers | Organization onboarding, team, KYC, payout account |
| **Supporting** | Finance | Fees, ledger, organizer balance, payouts, chargebacks |
| **Supporting** | Discovery | Search, storefront, categories (post-MVP) |
| **Generic** | Identity & Access | Login, OAuth, MFA (use an existing library/service) |
| **Generic** | Payments | Payment gateway integration (PIX, credit card) |
| **Generic** | Notifications | E-mail, push, WhatsApp |
| **Generic** | Fiscal | Service invoices (*NFS-e*) on platform fees (post-MVP) |

## Contexts

Each context section lists its aggregates, the invariants it owns, and the integration events it publishes and consumes. Contexts reference each other **only by id** and talk through integration events (or, in a few explicit cases, a synchronous application-level API).

### Identity & Access

- **Responsibility:** authentication, credentials, sessions, platform-level roles (e.g. platform admin).
- **Aggregates:** `Account` (id, e-mail, credentials, status).
- **Rule:** this context knows nothing about buyers or organizers. Every other context gives the person its own name and meaning (see [Ubiquitous language](#ubiquitous-language)).
- **Publishes:** `AccountRegistered`, `AccountDeactivated`.

### Organizers

- **Responsibility:** the organization that produces events. Covers members and their roles inside the organization, verification (KYC) and the bank account used for payouts.
- **Aggregates:**
  - `Organization`: owns `Member` entities (account id + role: owner, admin, staff, check-in operator) and `VerificationStatus`.
  - `PayoutAccount`: bank data / PIX key, verified status.
- **Invariants:**
  - An organization always has at least one owner.
  - An organization can sell **paid** tickets only if it is verified and has a verified `PayoutAccount`. Free events have no such requirement.
- **Publishes:** `OrganizationCreated`, `MemberAdded`, `MemberRemoved`, `OrganizationVerified`, `PayoutAccountVerified`.
- **Consumes:** `AccountDeactivated`.

### Event Management

- **Responsibility:** the event as a product. Covers title, description, category, venue (physical or online), period, age rating and cancellation policy.
- **Aggregates:** `Event`, with `Venue` and `EventPeriod` value objects.
- **Lifecycle:** `Draft → Published → (Postponed) → Cancelled | Finished`.
- **Invariants:**
  - Publishing requires a future period, a defined venue and an organization allowed to publish.
  - Once tickets have been sold, the period can only change through the **postponement** flow (which lets buyers request refunds). The venue cannot change silently.
  - A cancelled or finished event cannot be edited.
- **Publishes:** `EventPublished`, `EventPostponed`, `EventCancelled`, `EventFinished`.
- **Consumes:** `OrganizationVerified` (to keep a local copy of whether the organization may publish paid events).
- **Note:** ticket types, batches and prices **do not** live here. The event describes *what* happens; Sales decides *how it is sold*.

### Sales

- **Responsibility:** everything between "I want to buy" and "the order is paid".
- **Aggregates:**
  - `TicketOffer`: a ticket type for an event (e.g. "General", "VIP"), its `Batch`es (*lotes*: price, quantity, sales window), per-order limit and per-CPF limit.
  - `Allocation`: the inventory behind an offer. In the MVP the only implementation is `GeneralAdmission` (a counter per batch). A future `Seating` context will provide seat-level allocation.
  - `Reservation`: a temporary hold on inventory with a TTL (e.g. 15 minutes) while the buyer pays.
  - `Order`: buyer, `OrderItem`s (each with a mandatory `AttendeeInfo` value object: name, validated CPF, e-mail), amounts (ticket price, convenience fee, discount, total), status.
- **Invariants:**
  - Never sell beyond capacity, under concurrent purchases.
  - An expired reservation releases its inventory.
  - The next batch opens when the previous one sells out or when its start date arrives.
  - Per-CPF limit per event, even for free events, to prevent bots from draining inventory.
  - Every item has complete and valid attendee data before the order is placed.
  - An order with total `0` is confirmed immediately (`Order.confirm_without_payment()`), with no Payments involvement.
- **Publishes:** `TicketsReserved`, `ReservationExpired`, `OrderPlaced`, `OrderPaid`, `OrderCancelled`, `OrderRefunded`, `BatchSoldOut`, `OfferSoldOut`.
- **Consumes:** `EventPublished` (opens sales), `EventCancelled` (stops sales and cancels/refunds orders), `EventPostponed`, `PaymentConfirmed`, `PaymentFailed`, `RefundCompleted`.
- **Synchronous dependency:** asks Finance for the applicable `FeePolicy` to price the order.
- **Post-MVP:** coupons (`Coupon` aggregate) and half-price tickets (*meia-entrada*, with the legal 40% quota).

### Payments

- **Responsibility:** talking to the payment gateway, isolated behind an **Anti-Corruption Layer**. Gateway statuses, webhooks and idempotency keys never leak into other contexts.
- **Aggregates:** `Payment` (order id, method, amount, status, attempts), `Refund`.
- **Invariants:**
  - Webhooks are processed idempotently.
  - A refund never exceeds the captured amount.
- **Publishes:** `PaymentConfirmed`, `PaymentFailed`, `RefundCompleted`, `ChargebackOpened`, `ChargebackResolved`.
- **Consumes:** `OrderPlaced` (when total > 0), `OrderCancelled` / `OrderRefunded` (to issue refunds).

### Ticketing

- **Responsibility:** the ticket after the sale, as a right of entry. Covers issuance, named holder, transfer and invalidation.
- **Aggregates:** `Ticket` (event id, order id, `Holder`, signed code/QR, status: `Valid | Cancelled | Used`).
- **Invariants:**
  - A ticket has exactly one holder.
  - A transfer replaces the holder **and** issues a new code. The old code becomes invalid immediately.
  - Transfers are blocked for used or cancelled tickets, and within a configurable window before the event starts.
- **Publishes:** `TicketIssued`, `TicketTransferred`, `TicketCancelled`.
- **Consumes:** `OrderPaid` (issue one ticket per order item), `OrderCancelled` / `OrderRefunded` / `EventCancelled` (cancel tickets), `AttendeeCheckedIn` (mark as used).
- **Why separate from Sales:** an `Order` ends its life when it is paid; a `Ticket` keeps living (transfers, check-in).

### Check-in

- **Responsibility:** validating entry at the gate.
- **Model:**
  - `GuestList` per event: a projection of valid tickets (code, holder name, masked CPF).
  - `CheckIn` aggregate: ticket, gate, operator, device, timestamp.
- **Invariants:**
  - A ticket enters once (multi-entry tickets are a future option).
  - Only members with the check-in operator role for the event's organization can scan.
  - The operator can compare the holder's ID document with the ticket holder.
- **Publishes:** `AttendeeCheckedIn`, `CheckInRejected`.
- **Consumes:** `TicketIssued`, `TicketTransferred`, `TicketCancelled`, `MemberAdded` / `MemberRemoved`.
- **Post-MVP:** offline mode (download the guest list to the device, sync check-ins later, resolve conflicts).

### Finance

- **Responsibility:** money held by the platform on behalf of organizers.
- **Aggregates:**
  - `FeePolicy`: convenience fee paid by the buyer and/or service fee absorbed by the organizer.
  - `Ledger`: double-entry accounts (gateway cash, organizer balance, platform fee revenue, chargeback reserve) and immutable `JournalEntry`s.
  - `Payout`: transfer of an organizer's available balance to their `PayoutAccount`.
- **Invariants:**
  - Every journal entry balances (debits = credits). Entries are never edited, only reversed.
  - Funds for an event become available for payout only N days after `EventFinished`. This protects against cancellations and chargebacks.
  - Free orders produce no entries.
  - A cancelled event triggers mass refunds that are debited from the organizer's balance. The balance may go negative, which becomes a receivable.
- **Publishes:** `RevenueRecognized`, `FundsReleased`, `PayoutScheduled`, `PayoutPaid`.
- **Consumes:** `PaymentConfirmed`, `RefundCompleted`, `ChargebackOpened`, `ChargebackResolved`, `EventFinished`, `PayoutAccountVerified`.
- **MVP scope:** ledger + manual / semi-automatic payouts. Automatic payouts come later.

### Notifications

- Consumes events from all contexts and sends transactional messages: order confirmation, tickets, transfer, event postponed or cancelled, payout paid.
- No business rules beyond templates and delivery preferences.

### Post-MVP contexts

- **Seating:** `SeatMap` per venue layout and seat-level holds. Provides an `Allocation` implementation to Sales.
- **Discovery:** read-only search and storefront projection (Postgres FTS, Meilisearch or Elasticsearch), built from Event Management and Sales events.
- **Reporting:** organizer dashboards (sales per batch, real-time check-ins). Pure projection.
- **Fiscal:** service invoices on platform fees, driven by Finance events.
- **Waiting room:** queue in front of Sales for high-demand events.

## Context map

```
                     ┌───────────────────┐
                     │ Identity & Access │  upstream, Open Host Service
                     └─────────┬─────────┘
            conformist (account id only, in every context)
                               │
┌────────────┐  customer/   ┌──▼───────────────┐  customer/   ┌─────────┐   ACL    ┌─────────┐
│ Organizers │─────────────▶│ Event Management │─────────────▶│  Sales  │◀────────▶│Payments │───▶ Gateway
└─────┬──────┘  supplier    └────────┬─────────┘  supplier    └────┬────┘          └────┬────┘
      │                              │                     OrderPaid│                    │
      │                              │                             ▼                    │
      │                              │                       ┌───────────┐              │
      │                              │                       │ Ticketing │              │
      │                              │                       └─────┬─────┘              │
      │                              │                             ▼                    ▼
      │   members / operators        │                       ┌───────────┐        ┌─────────┐
      └──────────────────────────────┼──────────────────────▶│ Check-in  │        │ Finance │◀── Organizers
                                     │                       └───────────┘        └────┬────┘    (PayoutAccount)
                                     │                                                 │ FeePolicy
                                     │                                                 └──────▶ Sales
                                     ▼
                    Notifications / Discovery / Reporting  (downstream, consume events only)
```

- **Published Language:** integration events are versioned, lean contracts, separate from internal domain events.
- **Anti-Corruption Layer:** Payments ↔ gateway. Later also Fiscal ↔ invoice provider.
- **Customer/Supplier:** Organizers → Event Management → Sales. The downstream needs drive what the upstream publishes.
- **Conformist:** every context simply uses the `Account` id from Identity.
- The only synchronous calls are Sales → Payments (create a charge) and Sales → Finance (read the fee policy). Everything else is asynchronous.

## Main flows (sagas)

### Paid purchase

1. **Sales:** the buyer reserves tickets → `TicketsReserved`. Inventory is held, with a TTL.
2. **Sales:** the buyer fills in attendee data for each ticket and places the order → `OrderPlaced`.
3. **Payments:** creates the charge (PIX / card). The gateway webhook arrives → `PaymentConfirmed`.
4. **Sales:** `Order.mark_as_paid()` → `OrderPaid`.
5. In parallel:
   - **Ticketing:** issues one named ticket per item → `TicketIssued`.
   - **Finance:** books gateway cash, organizer balance and fee revenue.
   - **Notifications:** sends the confirmation and the tickets.
6. **Check-in:** adds the tickets to the guest list.

**Compensation:** if payment fails or the reservation expires → `PaymentFailed` / `ReservationExpired` → inventory is released and the order is cancelled.

### Free registration

1. **Sales:** reserve → place the order with attendee data. Total is `0`, so `Order.confirm_without_payment()` → `OrderPaid`.
2. Ticketing, Notifications and Check-in react exactly as in a paid purchase. Payments and Finance are not involved.

### Event cancellation

1. **Event Management:** `EventCancelled`.
2. **Sales:** stops sales and cancels all paid orders → `OrderCancelled`.
3. **Payments:** refunds each order → `RefundCompleted`.
4. **Ticketing:** cancels the tickets → `TicketCancelled` → **Check-in** removes them from the guest list.
5. **Finance:** reverses the entries and debits the organizer balance.
6. **Notifications:** informs buyers.

### Ticket transfer

1. **Ticketing:** the current holder transfers to a new person (name, CPF, e-mail). The holder is replaced, a new code is issued and the old code is invalidated → `TicketTransferred`.
2. **Check-in:** updates the guest list.
3. **Notifications:** sends the ticket to the new holder and a receipt to the old one.

## Ubiquitous language

The same human being has a different name, and a different model, in each context. Buyer ≠ attendee: one person can buy four tickets for friends.

| Context | Term | Meaning |
|---|---|---|
| Identity & Access | Account | Someone who can log in |
| Organizers | Member / Owner | A person working for an organization |
| Sales | Buyer | Who places and pays for the order |
| Sales | AttendeeInfo | Who will attend, as declared at checkout |
| Ticketing | Holder | Current owner of a ticket |
| Check-in | Attendee / Operator | Who enters / who scans |
| Finance | Payee | The organization receiving a payout |

Other terms:

- **Ticket offer:** a sellable ticket type of an event (e.g. "VIP").
- **Batch** (*lote*): a price tier of an offer, with its own quantity and sales window.
- **Convenience fee** (*taxa de conveniência*): fee paid by the buyer on top of the ticket price.
- **Payout** (*repasse*): transfer of the organizer's available balance to their bank account.
- **Half-price ticket** (*meia-entrada*): legally mandated discounted ticket (post-MVP).

## Architecture decisions

- **Modular monolith first.** Each bounded context is a package with `domain` / `application` / `infra` layers. There are no imports between domain layers of different contexts. Contexts communicate only through integration events or a context's public application API. Extracting a context into a service later stays cheap.
- **One database schema per context.** No cross-context joins or foreign keys; references are ids.
- **Transactional outbox** for integration events, so that state changes and published events are atomic. Consumers are idempotent.
- **Domain events ≠ integration events.** Domain events are internal and rich. Integration events are the public, versioned contract.
- **Inventory concurrency** is the main scaling risk. Use atomic counters (Redis or an atomic `UPDATE ... WHERE available >= n`) for reservations, with the `Batch` version as optimistic lock. Shard capacity for very large events, and add a waiting room (post-MVP).
- **Personal data (LGPD).** CPF and attendee data are personal data. Mask them in projections (guest list, reports), restrict access and define a retention policy.