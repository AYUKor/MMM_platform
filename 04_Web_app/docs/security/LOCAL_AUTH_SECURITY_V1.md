# Local Auth Security v1

## Scope

This control set protects a single-node research pilot. It is a real local
authentication implementation, but not a substitute for approved corporate
SSO, MFA, centralized secrets, SIEM or company IAM governance.

## Implemented controls

- Argon2id password hashing with configurable cost and rehash-on-login;
- password policy: 12-256 characters, at least one letter and one digit;
- no plaintext password storage, logging or API response;
- random 256-bit-class opaque session token;
- only an HMAC-SHA-256 token digest is stored in SQLite;
- session secret comes only from environment and is excluded from config hash,
  runtime card and Git;
- absolute and idle session expiration;
- `HttpOnly`, `SameSite=Lax`, scoped `Path=/api/v1` cookie;
- `Secure` cookie required by the research-pilot profile;
- explicit credentialed CORS allowlist;
- Origin and Host validation on POST/PATCH;
- per-identity/client login window and cooldown;
- self-service registration (owner decision 2026-07-23) limited to the
  `analyst` role with any email domain; administrative roles remain
  admin-assignable only;
- registration shares the login attempt window/cooldown rate limit;
- duplicate-email registration returns a generic, non-confirming error and
  the audit log never stores attempted emails;
- every successful self-registration appends a `user_self_registered` audit
  event;
- generic unknown-email/wrong-password response;
- centralized permission guard with separate `401` and `403`;
- field/action-level admin enforcement: profile/status changes require
  `admin.users.write`, role assignment requires `admin.roles.write`, and
  session revocation requires `admin.sessions.write`;
- every auth/admin response, including errors, carries
  `Cache-Control: no-store`, `Pragma: no-cache` and
  `X-Content-Type-Options: nosniff`;
- last-admin, self-disable and disable-revokes-session invariants;
- append-only browser-safe audit log;
- auth directory mode `0700` and SQLite file mode `0600` where supported.

## Secret handling

`MMM_AUTH_SESSION_SECRET` must be at least 32 random characters. Bootstrap email
and password are temporary environment values used by an explicit CLI command.
They must be unset after bootstrap and must not be placed in tracked shell,
JSON, Markdown or service files.

## Known pilot limitations

- one SQLite file and one application node;
- self-registration is open to anyone who can reach the service over the
  network; there is no email confirmation, invitation flow or corporate
  account lifecycle check, so network reachability is the only gate;
- no MFA, password recovery email or password rotation workflow;
- no Redis/shared session service;
- rate limiting is process/database local and keyed by normalized identity plus
  directly observed client address;
- SQLite is not encrypted at rest by the application;
- audit export, SIEM forwarding and alerting are absent;
- no corporate account lifecycle, group mapping or emergency-access process;
- reverse-proxy and host hardening remain deployment responsibilities.
