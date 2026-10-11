# Identity

Identity & Access bounded context (generic subdomain).

Handles authentication: accounts, credentials, sessions and platform-level roles. It only knows that an `Account` exists; it knows nothing about buyers or organizers, since each context gives the person its own name and meaning.

See [bounded_contexts.md](../../var/docs/bounded_contexts.md#identity--access).
