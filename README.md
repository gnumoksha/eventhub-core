# EventHub

EventHub is the backend for an event management and ticketing platform inspired by services such as Eventbrite and Sympla. It aims to be a demonstration of a complex product built with production-ready technology.

The repository is under active development. Its contexts and contracts are organized to support an end-to-end product; see the code and the [roadmap](var/docs/roadmap.md) for implementation progress.

## Technology stack

- Python 3.14 and [uv](https://docs.astral.sh/uv/) for the workspace and dependency management
- FastAPI for the HTTP API
- SQLModel, async SQLAlchemy, and PostgreSQL for persistence
- RabbitMQ for integration events and Redis for tasks such as temporary reservations and login attempt tracking
- Celery for asynchronous tasks
- Docker Compose for the local environment
- Kubernetes for the production environment

## Architecture

The system is a **modular monolith**: business contexts are separate packages but run as one application. This structure preserves domain boundaries without requiring each context to run as a distributed service.

### Contexts

Each package under `packages/` represents a bounded context and contains `domain`, `application`, and `infra` layers as needed under `src/<context>/`:

| Package         | Responsibility                                           |
| --------------- | -------------------------------------------------------- |
| `identity`      | Accounts, authentication, and sessions                   |
| `organizers`    | Organizations, members, verification, and payout details |
| `events`        | Event registration, publication, and lifecycle           |
| `sales`         | Offers, batches, inventory, reservations, and orders     |
| `payments`      | Charges, payment gateway integration, and refunds        |
| `ticketing`     | Ticket issuance, ownership, transfers, and cancellation  |
| `checkin`       | Ticket validation at the venue                           |
| `finance`       | Fees, ledger, and payouts                                |
| `notifications` | Transactional messages triggered by business flows       |
| `reporting`     | Projections and reporting queries                        |
| `shared`        | Shared application infrastructure                        |
| `libs`          | Reusable libraries independent of the framework          |

Dependencies between domains are limited: contexts do not import other contexts' domain models or join their data. Each context has its own PostgreSQL schema and refers to entities in other contexts by ID. Contexts communicate primarily through integration events; explicit synchronous dependencies live in the application or infrastructure layers.

### Layers and events

- **Domain:** contains business rules, invariants, entities, and value objects. Domain methods receive the current time as an argument instead of reading the system clock directly.
- **Application:** coordinates use cases, repositories, and the clock; event handlers and tasks also live here.
- **Infrastructure:** implements persistence, the HTTP API, messaging, and external integrations.

State changes and published events are stored together through a **transactional outbox**. The `outbox-relay` process sends pending events to the `events` exchange in RabbitMQ; each context's consumers dispatch events to registered listeners. Delivery is at least once, so handlers must be idempotent.

### Simplified paid purchase flow

1. `sales` reserves inventory and creates an order with attendee details.
2. `payments` starts the charge and publishes the result received from the gateway.
3. After confirmation, `sales` confirms the order and publishes `OrderPaid`.
4. `ticketing`, `finance`, `notifications`, and `checkin` react to the event by issuing tickets, recording amounts, notifying the buyer, and updating the guest list.

Free orders are confirmed without going through `payments`. Domain decisions and complete flows are documented in [bounded_contexts.md](var/docs/bounded_contexts.md); context-specific patterns and decisions may also be documented in each package's ADRs.

## Run locally

You need Docker and Docker Compose installed. Compose starts the API and its infrastructure services:

```bash
docker compose up -d
```

The API is available at `http://localhost:8000`. In development, the OpenAPI document is available at `http://localhost:8000/openapi.json` and the GUI is at `http://localhost:8000/docs`.

To stop the services:

```bash
docker compose down
```

## Tests and tools

Run Python commands inside the `app-web` container. Run tests one package at a time because each package has its own test module:

```bash
docker compose exec -e APP_ENV=test app-web uv run pytest packages/identity/tests
docker compose exec -e APP_ENV=test app-web uv run pytest packages/events/tests
```

To run a specific test:

```bash
docker compose exec -e APP_ENV=test app-web uv run pytest packages/identity/tests/application/authentication_test.py::test_name
```

Other useful commands:

```bash
docker compose exec app-web uv run ruff check packages/ src/
docker compose exec app-web uv run ty check --error-on-warning bin/ packages/ src/ --exclude packages/libs/tests
docker compose exec app-web uv run alembic upgrade head
```

Always set `APP_ENV=test` when running tests so they use the test database, which is separate from the development database.

## Documentation

- [Architecture and context map](var/docs/bounded_contexts.md)
- [Roadmap](var/docs/roadmap.md)
- [Architecture decision records (ADRs)](packages/identity/var/docs) in `packages/**/var/docs/`
