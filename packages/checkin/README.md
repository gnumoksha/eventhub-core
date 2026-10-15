# Check-in

Check-in bounded context (core subdomain).

Validates entry at the event gate. It keeps a guest list of valid tickets per event and records each check-in (ticket, gate, operator, device), making sure a ticket enters only once. Offline operation comes after the MVP.

See [bounded_contexts.md](../../var/docs/bounded_contexts.md#check-in).
