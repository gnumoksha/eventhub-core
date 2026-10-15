# Shared

Code shared among the bounded contexts: settings, database session, dependency injection, logging, observability, domain events setup, the transactional outbox and base domain errors.

It must stay free of business rules from any specific bounded context. This is not a bounded context.
