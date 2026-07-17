# ADR 0020: local auth and future SSO boundary v1

## Status

Accepted for the research pilot. This is not a corporate IAM approval.

## Context

Phase A-D exposed real campaign, calculation, result, model and navigation
contracts, but any browser that reached the service received the same access.
Phase E needs real login, server-side sessions and role-based permissions
without coupling the product API to one future corporate SSO vendor.

## Decision

The HTTP layer depends on an `IdentityProvider` protocol. The current
`LocalPilotIdentityProvider` implements email/password authentication. A future
OIDC/SAML adapter must implement the same boundary and produce the same
`RequestContext`; no fake corporate provider is included.

```text
browser
  -> HttpOnly opaque session cookie
  -> IdentityProvider
       -> LocalPilotIdentityProvider (implemented)
       -> corporate SSO adapter (not implemented)
  -> RequestContext(user, session, permissions, request_id)
  -> centralized AuthorizationGuard
  -> existing Phase A-D handler
```

The local provider composes separate repositories for users, sessions, login
attempts and append-only audit events. They share one SQLite database so admin
invariants and session revocation can be committed atomically.

## Passwords and sessions

- passwords use Argon2id through `argon2-cffi`;
- the hash records Argon2 parameters and is rehashed after a successful login
  when configured parameters change;
- the minimum local password policy is 12-256 characters, at least one letter
  and one digit;
- the browser receives a random opaque token only in an `HttpOnly` cookie;
- SQLite stores an HMAC-SHA-256 digest of that token, never the token itself;
- absolute and idle expiry are checked server-side;
- disable and explicit revoke invalidate sessions immediately.

## Authorization

Routes are mapped centrally to versioned permissions. Handlers do not compare
role names. `viewer`, `analyst` and `admin` are only maintained role bundles;
the session response contains the authoritative permissions for the frontend.

The administrative service performs a second action-level check after route
authentication: `admin.users.write` covers profile/status changes,
`admin.roles.write` covers every role assignment, and
`admin.sessions.write` covers session revoke. A route-level users permission
therefore cannot be used to smuggle `role_id` through a mutation payload.

Anonymous access is limited to login, session check, liveness and readiness.
Authentication failure is `401`; an authenticated user without a required
permission receives `403`.

## CSRF and CORS

State-changing browser requests require:

1. an `Origin` exactly present in the configured allowlist;
2. a valid `Host` for localhost or the configured public HTTPS origin;
3. a `SameSite=Lax`, `HttpOnly` cookie;
4. credentialed CORS only for the explicit allowlist.

This pilot uses strict Origin/Host validation rather than a JavaScript-readable
CSRF token. `Secure` cookies are mandatory for the research-pilot profile.
GET requests do not change product state. Session last-seen bookkeeping and
required audit entries are security side effects, not product mutations.

Auth/admin responses and errors are explicitly non-cacheable through
`Cache-Control: no-store` and `Pragma: no-cache`; API responses also send
`X-Content-Type-Options: nosniff`.

## Consequences

- local development and one-node research pilot receive real access control;
- MMM, forecast, optimizer and recommendation policy remain unchanged;
- switching to SSO does not require changing frontend permissions or product
  result contracts;
- SQLite is intentionally a single-node pilot store;
- MFA, recovery email, self-registration and password reset are absent;
- the local provider is not a claim of company-contour readiness.
