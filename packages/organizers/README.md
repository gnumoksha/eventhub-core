# Organizers

Organizers bounded context (supporting subdomain).

Manages the organizations that produce events: their members and roles (owner, admin, staff, check-in operator), verification (KYC) and the payout account (bank data / PIX key). Only a verified organization with a verified payout account can sell paid tickets.

See [bounded_contexts.md](../../var/docs/bounded_contexts.md#organizers).

The context stores legal names, CPF/CNPJ and payout details encrypted at rest. Configure
a dedicated Fernet key in `PERSONAL_DATA_ENCRYPTION_KEY`; do not reuse `APP_SECRET`.
Keep a protected backup of this key: stored personal data cannot be decrypted after the
key is lost or replaced without re-encrypting the data first.
