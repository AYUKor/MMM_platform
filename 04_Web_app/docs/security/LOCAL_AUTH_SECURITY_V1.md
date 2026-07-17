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
- no MFA, password recovery email, password rotation workflow or
  self-registration;
- no Redis/shared session service;
- rate limiting is process/database local and keyed by normalized identity plus
  directly observed client address;
- SQLite is not encrypted at rest by the application;
- audit export, SIEM forwarding and alerting are absent;
- no corporate account lifecycle, group mapping or emergency-access process;
- reverse-proxy and host hardening remain deployment responsibilities.
