# Auth Session Contract v1

## Purpose

The browser asks the backend who is signed in and receives ready-to-use
permissions. It must not infer permissions from `role_id`, store a password or
read the session token.

## Endpoints

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/v1/auth/login` | Verify local credentials and create a server-side session |
| `GET` | `/api/v1/auth/session` | Return authenticated or anonymous `auth_session_v1` |
| `POST` | `/api/v1/auth/logout` | Idempotently revoke the current session and clear the cookie |

Login body:

```json
{"email": "user@example.org", "password": "not-shown-in-logs"}
```

Authenticated response:

```json
{
  "contract_name": "auth_session_v1",
  "schema_version": "1.0.0",
  "authenticated": true,
  "user": {
    "user_id": "usr_0123456789abcdef01234567",
    "display_name": "Пользователь",
    "email": "user@example.org",
    "role": {"role_id": "analyst", "title": "Аналитик"},
    "permissions": ["workspace.read", "calculation.read"],
    "status": "active"
  },
  "session": {
    "session_id": "ses_0123456789abcdef01234567",
    "created_at_utc": "2026-07-17T10:00:00+00:00",
    "expires_at_utc": "2026-07-17T18:00:00+00:00",
    "last_seen_at_utc": "2026-07-17T10:00:00+00:00",
    "idle_timeout_seconds": 3600
  }
}
```

Anonymous response keeps the same top-level shape with `authenticated=false`
and null `user`/`session`. The opaque cookie token and password hash are never
returned in JSON.

## Browser behavior

- send requests with credentials enabled;
- use `user.permissions` as the only UI capability source;
- on `AUTH_REQUIRED` or `AUTH_SESSION_EXPIRED`, open the login flow;
- on `PERMISSION_DENIED`, keep the session and show a no-access state;
- use the same generic text for an unknown email and a wrong password;
- do not persist the response as a replacement for checking `/auth/session`.

The schema is available as
`GET /api/v1/contracts/auth-session-v1.json` to an authenticated user with
`help.read`.
