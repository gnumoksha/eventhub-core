# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Event management and ticketing platform (similar to Sympla), built as a **modular monolith**: FastAPI + SQLModel (async, PostgreSQL), RabbitMQ for integration events, Celery for tasks, Python 3.14, uv workspace.

## Commands

Run uv, ruff, ty, alembic and pytest **inside the Docker container**, never on the host:

```bash
docker compose up -d                                              # app-web, outbox-relay, events-consumers, postgresql, redis, rabbitmq
docker compose exec app-web uv run pytest packages/events/tests   # tests of one package
docker compose exec app-web uv run pytest packages/events/tests/domain/event_test.py::test_name   # a single test
docker compose exec app-web uv run ruff check packages/ src/
docker compose exec app-web uv run ruff format bin/ packages/ src/
docker compose exec app-web uv run ty check --error-on-warning bin/ packages/ src/ --exclude packages/libs/tests
docker compose exec app-web uv run alembic upgrade head
docker compose exec app-web uv run alembic revision --autogenerate -m "message"
docker compose exec -T -e APP_ENV=test app-web uv run alembic upgrade head   # migrate the test database
```

- Run pytest **one package at a time**, as CI does (`.github/workflows/test.yml`). Every package has its own top-level `tests` package (tests do `from tests.conftest import ...`), so collecting several packages in one run makes them collide.
- Test files are named `*_test.py`. CI runs with `-m "not llm_access"`.
- The test database (`eventhub_test`) is created by `var/docker/postgresql/initdb.d/init-test-db.sh`; settings come from `.env` + `.env.test` when `APP_ENV=test`.

## Architecture

Read `var/docs/bounded_contexts.md` before designing anything: it is the domain model (contexts, aggregates, invariants, integration events each context publishes and consumes, sagas, ubiquitous language). `var/docs/roadmap.md` sequences the work. Context-specific decisions (ADRs) live in `packages/<context>/var/docs/`.

### Layout

- `packages/<context>/` — one uv workspace package per bounded context: `identity`, `organizers`, `events` (Event Management), `sales`, `payments`, `ticketing`, `checkin`, `finance`, `notifications`, `reporting`. Each has `src/<context>/{domain,application,infra}`, `tests/`, `bin/events_consumer.py` and `var/docs/`. `events` is the most complete context and the reference for new code.
- `packages/shared/` — app infrastructure shared by contexts: settings, async DB session, transactional outbox, RabbitMQ topology, Celery app, DI, logger, Sentry.
- `packages/libs/` — framework-agnostic libraries (`libs.events`: event base class, encoding, dispatchers, RabbitMQ consumer; `libs.time_utils`: `Clock`/`FakeClock`).
- `src/eventhub_core/main.py` — the FastAPI app: calls `setup_routers(app)` and `load_listeners(<context>.application)` for every context.
- `bin/outbox_relay.py` — publishes outbox messages to RabbitMQ. `Procfile` (run by honcho in the `events-consumers` container) starts one events consumer per context.
- `migrations/` — a single Alembic history for all contexts. New table modules must be imported in `migrations/env.py` to be picked up by autogenerate.

### Boundaries

- No imports between the `domain` layers of different contexts. Contexts reference each other **only by id** and talk through integration events or a context's public application API.
- One PostgreSQL schema per context (`__table_args__ = {"schema": "<context>"}`). No cross-context joins or foreign keys.
- Other contexts never use Identity's models. They authenticate through `identity.infra.http.authentication` (`CurrentAccountID`, `CSRFDep`), imported only from their `infra/http` layer, and receive a plain `uuid.UUID`. Authentication uses opaque database sessions in an HTTP-only cookie (see `packages/identity/var/docs/adr-0001-opaque-database-sessions.md`). Authorization ("is this account a member of the organization?") belongs to each context, not Identity.

### Aggregate pattern (see `events/domain/models/event/`)

- The aggregate is a SQLModel `table=True` class. Domain entity and persistence model are the **same class**. State changes go only through its methods, which validate explicitly (table models skip Pydantic validation) and take `now: datetime` instead of reading the clock.
- Optimistic locking via a `version` column (`version_id_col`); the repository turns `StaleDataError` into `shared.domain.errors.ConcurrencyConflict`.
- Methods record integration events (`PublishableEvent` subclasses in `events.py`, named `eventhub:<context>:<aggregate>.<verb>`, with explicit `to_dict`/`from_dict`). The repository's `save()` calls `add_to_outbox(session, aggregate.pull_events())` before committing, so state and events are atomic. Delivery is at-least-once, so listeners must be idempotent.
- `values.py` holds value objects and id aliases (e.g. `OrganizationID = uuid.UUID`).
- Application services (`application/<aggregate>/service.py`) receive the repository and a `Clock`, and are exposed with `Annotated[..., Depends(...)]` aliases (`XxxServiceDep`). Event handlers are registered with `@listener(EventClass)` in `application/**/listeners.py`; Celery tasks go in `application/**/tasks.py` and must be listed in `shared/infra/tasks.py`.
- Service tests use an in-memory subclass of the concrete repository (see `events/tests/conftest.py`). HTTP tests build a bare `FastAPI()` with the context's `setup_routers` and override dependencies (including `require_account_id` and `require_csrf`).

## Conventions

- Do not create an abstract repository if only one implementation exists: it is harder for an LLM to find the code.
- Do not split the domain entity from its infrastructure implementation, to avoid complexity and keep it easy to find.
- Use UUID v7 for ids (`uuid_utils.compat.uuid7`), unless specified otherwise.
- Write code and docs in English.
- `.agents/skills/` has FastAPI and SQLModel reference skills.
