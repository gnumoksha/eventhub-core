# Architectural Challenges

This document outlines the core architectural and engineering challenges inherent to designing a high-scale event management and ticketing platform (similar to Sympla and Eventbrite), along with mitigation strategies and architectural patterns.

---

## 1. High-Concurrency Inventory Reservation & Flash Sales

### The Challenge
When tickets for highly anticipated events or early-bird batches go live, thousands of users compete for limited quotas simultaneously (thundering herd problem). Traditional database transactions (`SELECT ... FOR UPDATE` or serializable isolation) create severe row-lock contention, database connection pool exhaustion, and elevated latency, which can lead to cascading failures or accidental overselling.

### Requirements & Failure Modes
* **Zero Overselling:** Selling more tickets than physical or legal venue capacity results in financial and legal liabilities.
* **Temporary Stock Holds (TTL):** When a user enters checkout, tickets must be reserved for a bounded window (e.g., 10–15 minutes) and automatically released if the purchase is abandoned or payment expires.
* **Fair Allocation:** Ensuring first-come, first-served semantics without race conditions.

### Architectural Strategies
* **In-Memory Atomic Quotas (Redis + Lua):**
  Maintain available quotas per batch in Redis. Use atomic Lua scripts (`DECRBY` with floor check) to hold stock instantly in sub-millisecond time.
* **Distributed Reservation with TTL:**
  Store the active reservation key with a time-to-live (`EXPIRE reservation:{order_id} 900`). If payment confirmation does not arrive before expiry, a background worker or Redis keyspace notification replenishes the ticket pool.
* **Decoupled Relational Persistence:**
  Only after the in-memory reservation succeeds does the application generate the pending order in PostgreSQL.
* **Virtual Waiting Room (Queue Gatekeeper):**
  For tier-1 mega events, place incoming traffic behind a rate-limiting queue (e.g., token bucket admission queue) before users reach the inventory service.

---

## 2. Offline-First Access Control & Check-in Resilience

### The Challenge
Event venues (arenas, stadiums, festivals, underground clubs) frequently experience congested cellular networks, power interruptions, or nonexistent Wi-Fi. Gate staff cannot rely on synchronous round-trips to a central API to validate each attendee's ticket.

### Requirements & Failure Modes
* **Sub-Second Gate Validation:** Check-in processing must take $< 300\text{ ms}$ per attendee to prevent bottlenecks at the turnstiles.
* **Offline Fraud Prevention:** Prevent forged QR codes and detect duplicate scans across multiple entry gates.
* **Eventual Reconciliation:** Seamlessly synchronize offline check-in logs back to the central platform once connectivity resumes.

### Architectural Strategies
* **Asymmetrically Signed QR Codes:**
  Instead of holding plain database UUIDs, vouchers contain a cryptographically signed payload (using Ed25519 or compact JWT-like format):
  $$\text{Payload} = \{\text{ticket\_id}, \text{event\_id}, \text{batch\_id}, \text{attendee\_hash}, \text{nonce}\}_{\text{private\_key}}$$
  Gate devices download the organizer's public key prior to the event and can authenticate the ticket validity completely offline.
* **Local Device Cache & Fast Invalidation:**
  Gatekeeper devices synchronize the snapshot of valid ticket hashes before gates open. Local SQLite or embedded databases record scanned state.
* **Peer-to-Peer Local Mesh or Hub-and-Spoke Gateway:**
  Multiple scanners at a venue can communicate over a local offline LAN/Wi-Fi router to synchronize scanned tickets in real time, synchronizing with the cloud asynchronously.
* **Idempotent Check-in Ingestion:**
  Check-in events record device timestamps and monotonic sequencing. The central database processes them via idempotent upserts (`ON CONFLICT DO NOTHING`) to resolve duplicate scans gracefully.

---

## 3. Asynchronous Checkout, Payment Gateways & Split Billing

### The Challenge
Ticketing involves heterogeneous payment rails (instant payments like PIX, credit cards with asynchronous 3DS verification, and delayed bank slips/boleto). Webhooks from payment gateways can arrive out-of-order, be duplicated, or arrive after the user has closed their browser. Furthermore, ticketing requires complex marketplace splits between platform fees, organizer net revenue, affiliate shares, and taxes.

### Requirements & Failure Modes
* **Double Payment / Phantom Authorizations:** Charges occurring after a reservation has expired, or multiple webhooks processing the same payment twice.
* **Dual-Write Hazards:** A transaction is charged in the gateway, but the internal system fails to record the ticket issuance due to a network or database failure.
* **Auditable Financial Ledger:** Immutable ledger tracking every credit, fee, refund, and payout.

### Architectural Strategies
* **Transactional Outbox Pattern:**
  State changes (e.g., `OrderPaid`) and outgoing events are committed within the same database transaction. A separate relay process (or CDC pipeline) publishes domain events to RabbitMQ/Celery, guaranteeing at-least-once message delivery.
* **Strict Webhook Idempotency:**
  Store processed gateway transaction IDs (`payment_events` with unique constraints). Redundant webhooks return HTTP 200 immediately without executing business logic.
* **Two-Phase Payment Handling:**
  1. Authorize / Capture webhook received.
  2. Transition order status from `PENDING` to `PAID`.
  3. Emit `OrderCompleted` to trigger voucher generation, email dispatch, and ledger entries asynchronously.
* **Automated Expiry Sweeper & Compensation:**
  Periodic scheduler cancels orders whose payment window expired without receipt. If a late webhook arrives for an expired order, trigger an automated gateway refund rather than issuing an invalid ticket.

---

## 4. Multi-Tenant Role-Based Access Control (RBAC)

### The Challenge
A user on the platform possesses dual identities: they can be an attendee/buyer in one event, an event owner/organizer in another, and a gatekeeper staff member with limited permissions in a third event. Global roles (like `ADMIN` or `USER`) are insufficient.

### Requirements & Failure Modes
* **Contextual / Scoped Permissions:** A user must only access administrative and financial data for events they explicitly own or collaborate on.
* **Role Delegation:** Organizers need to invite team members with granular scopes (e.g., `FINANCIAL_VIEWER`, `TICKET_MANAGER`, `GATE_SCANNER`).
* **Tenant Isolation:** Accidental data leakage between different organizers must be prevented at the database and application levels.

### Architectural Strategies
* **Event-Scoped RBAC:**
  Model authorization around an explicit membership entity:
  `User` $\leftrightarrow$ `EventMembership` $\leftrightarrow$ `Role` (with specific permission sets).
* **Tenant Context Middleware / Injectable Dependencies:**
  Inject the authenticated user's permission set into the request lifecycle scoped to the target `event_id`.
* **Row-Level Security (RLS) or Query Filtering:**
  Enforce tenant boundaries across all database queries by consistently applying organizer or event foreign key predicates.

---

## 5. Event-Driven Decoupling & Eventual Consistency

### The Challenge
The purchase completion lifecycle involves multiple sub-domains:
1. `Billing`: confirms payment.
2. `Ticketing`: transitions reservations into permanent allocations.
3. `Orders`: marks order as fulfilled.
4. `AccessControl`: generates vouchers and cryptographic QR codes.
5. `Notifications`: sends confirmation emails with PDF tickets attached.
6. `Analytics`: records conversions, traffic sources, and gross merchandise value (GMV).

Executing all of these synchronously inside an HTTP request produces high latency, poor availability (if email provider is slow, checkout fails), and tight coupling.

### Architectural Strategies
* **Domain Events via Message Broker:**
  Publish discrete domain events (`OrderCreated`, `PaymentReceived`, `TicketIssued`, `TicketCheckedIn`) via RabbitMQ.
* **Independent Consumers:**
  * `NotificationService` listens to `OrderCompleted` to render PDFs and send emails asynchronously.
  * `AnalyticsService` listens to sales and check-in events to populate read-optimized read models and dashboards.
* **Dead Letter Queues (DLQ) & Retry Policies:**
  Implement exponential backoff for external integrations (e.g., email deliverability, SMS) with dead-letter storage for manual inspection and replayability.

---

## 6. Read-Heavy Catalog & Semantic Event Discovery

### The Challenge
Event listings and discovery pages have a high read-to-write ratio ($> 100:1$). Users search by geographic proximity, date ranges, categories, and natural language semantic queries (e.g., *"outdoor jazz festivals this weekend"*).

### Architectural Strategies
* **CQRS (Command Query Responsibility Segregation):**
  Separate the transactional relational write models (SQLModel / PostgreSQL) from read-optimized query models.
* **Dedicated Search Engine Integration:**
  Synchronize published event data into a dedicated search engine (e.g., Meilisearch / Elasticsearch) using event listeners, keeping full-text and geospatial search off the primary OLTP database.
* **Multi-Layered Caching:**
  Cache public event landing pages and ticket availability summaries at the CDN edge and in Redis, with invalidation triggers when batch inventory or event details change.
