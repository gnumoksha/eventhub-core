# ADR 0001: Opaque sessions stored in the database for authentication

- **Status:** Accepted
- **Date:** 2026-10-20
- **Context owner:** Identity & Access

## Context

After a successful login, the server must hand the client something that proves who it is on the following requests, and every request must turn that proof into an `AccountID`.

Constraints that shape the decision:

- **Instant revocation is required.** Logout, "log out of all devices", password changes and `AccountDeactivated` (see [bounded_contexts.md](../../../../var/docs/bounded_contexts.md#identity--access)) must take effect on the very next request. The platform holds buyers' tickets and organizers' money, so a stolen credential that keeps working until it expires is not acceptable.
- **Modular monolith first.** Every context runs in the same process and uses the same database (one schema per context). Verifying tokens without a database, across separate services, brings no benefit today.
- **Bounded contexts.** Other contexts only need to know *who* is calling (an `AccountID`). They must not read Identity's tables or depend on how sessions are implemented.
- **Browser clients first.** The main clients are web front-ends, so cookies (`HttpOnly`, `Secure`, `SameSite`) are available.

## Options considered

### 1. Opaque session stored in the database

The cookie holds a random string with no meaning of its own (e.g. `session=Xk3f9...`). The server finds the account by looking the token up.

```
login:   token = secrets.token_urlsafe(32)
         INSERT INTO identity.sessions (id, account_id, token_hash, expires_at, revoked_at)
         Set-Cookie: session=<token>; HttpOnly; Secure; SameSite=Lax

request: hash(cookie) -> SELECT account_id FROM identity.sessions
                         WHERE token_hash = ? AND revoked_at IS NULL AND expires_at > now()
```

- ✅ The server is in control. Revoking a session (or all of an account's sessions) is a single `UPDATE ... SET revoked_at = now()`, and it takes effect on the next request.
- ✅ Only a hash of the token is stored, like a password, so a leaked database dump cannot be used to impersonate anyone.
- ✅ The client learns nothing: the token is a random string.
- ❌ One indexed lookup per authenticated request. That is cheap in a monolith, and the lookup can move to Redis later if needed.

### 2. JWT (stateless signed token)

A signed JSON document such as `{"sub": "<account_id>", "exp": 1760000000}`. The server checks the signature and trusts the contents without querying the database.

- ✅ No lookup per request, and any service holding the key can verify it. This is useful with many separate services or a third-party identity provider.
- ❌ **It cannot be revoked.** The token stays valid until `exp`, even after logout or deactivation. The usual fixes (a short-lived access token plus a refresh token stored in the database, or a denylist) bring server-side state back, so you pay for both approaches.
- ❌ Claims (status, roles) are frozen in the token until it expires.
- ❌ The contents are signed, not encrypted, so the client can read them.

### 3. Starlette's `SessionMiddleware` cookie (currently added in `main.py`)

`request.session` (a dict) is serialized, signed with `itsdangerous` using `APP_SECRET`, and stored entirely in the cookie. Login would be `request.session["account_id"] = str(account_id)`.

- ✅ Already set up, and trivial to use.
- ❌ **Same revocation problem as a JWT.** The data lives in the browser, and the server accepts any cookie with a valid signature. Logout only asks the browser to delete its copy. A stolen copy keeps working until it expires, and the only server-side kill switch is rotating `APP_SECRET`, which logs out every user.
- ❌ The contents are signed but not encrypted (they are base64), so the client can read them.
- ❌ In effect it is a JWT in a different format, without a standard `exp` or audience checks.

### Summary

| | Revoke instantly | DB/Redis hit per request | Contents visible to the client | Good fit |
|---|---|---|---|---|
| Opaque DB session | ✅ | yes (cheap) | nothing (random string) | Monolith, browser clients |
| JWT | ❌ (unless you add state) | no | yes (signed, readable) | Many services, external identity provider |
| `SessionMiddleware` | ❌ | no | yes (signed, readable) | Small transient state, not auth |

## Decision

Use **opaque sessions stored in the `identity` schema** (option 1).

- `Session` is an entity of the Identity context (`identity.sessions` table): `id` (uuid7), `account_id`, `token_hash`, `created_at`, `expires_at`, `revoked_at`.
- The raw token is generated with `secrets.token_urlsafe(32)`, returned once in the cookie, and never stored. Only its hash is persisted.
- Sessions expire after seven days. The host-only cookie uses `HttpOnly; Secure; SameSite=Lax; Path=/`; local development uses a non-`__Host-` cookie because it may not use HTTPS.
- Logout revokes the current session. `AccountDeactivated` and password changes revoke all of the account's sessions.
- Signup creates an unverified account and session. Unverified sessions can use identity and email-verification routes; other protected routes require a verified email.
- Email verification and password reset tokens are single-use and stored as hashes with 24-hour and one-hour expiries respectively. Delivery events carry an authenticated-encrypted token, not the raw token.
- State-changing authenticated browser requests require a session-bound CSRF token in `X-CSRF-Token` and a trusted `Origin`. The token is returned at login or fetched from `/identity/csrf`.
- Passwords use Argon2id, accept 8–128 characters, and have no composition requirements. Login attempts are throttled in Redis after three failures for an email/IP pair in 15 minutes, with a 15-minute backoff.
- Other contexts authenticate through Identity's public application API, never by reading `identity.sessions`:

  ```python
  # identity/application/authentication.py
  CurrentAccountID = Annotated[uuid.UUID, Depends(require_account_id)]
  ```

  They import it only from their `infra/http` layer, and receive a plain `uuid.UUID` (conformist relationship).
- `SessionMiddleware` is **not** used for authentication. It may still hold short-lived, low-stakes state, such as the OAuth `state`/nonce during a redirect.

## Consequences

- Every authenticated request makes one indexed query on `identity.sessions` (by `token_hash`). It can be cached or moved to Redis if it ever becomes a bottleneck.
- Expired and revoked sessions pile up. A periodic task should delete them.
- Verification and password-reset events require a Notifications consumer to decrypt the token and deliver the email. The encrypted token uses `APP_SECRET`, so rotating that secret invalidates pending delivery events.
- Cookie-based authentication requires CSRF care: `SameSite=Lax` and a strict CORS configuration. Since `allow_credentials=True` is set, `CORS_ALLOW_ORIGIN_REGEX` must not match origins we do not control.
- If Identity is extracted into its own service, or mobile clients are added, the same opaque token can be sent as `Authorization: Bearer <token>`. Only `require_account_id` changes; the other contexts keep using `CurrentAccountID`.
- If we later move to an external identity provider (Keycloak, Zitadel, Auth0, ...), this ADR should be revisited. Identity would become an anti-corruption layer mapping the provider's subject to an `AccountID`.
