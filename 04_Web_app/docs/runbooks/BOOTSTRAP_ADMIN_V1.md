# Runbook: bootstrap local administrator v1

## Why this exists

There is no self-registration and no committed default password. Before the
first login, an operator creates exactly one local pilot administrator through
the CLI. The command writes only an Argon2id hash and an audit event.

## 1. Prepare environment

Use values outside Git. The session secret must contain at least 32 random
characters and remain stable across backend restarts.

```bash
export MMM_AUTH_MODE=local
export MMM_AUTH_SESSION_SECRET='<random-secret-at-least-32-characters>'
export MMM_AUTH_BOOTSTRAP_ADMIN_EMAIL='admin@example.org'
export MMM_AUTH_BOOTSTRAP_ADMIN_PASSWORD='<temporary-strong-password>'
export MMM_AUTH_BOOTSTRAP_ADMIN_NAME='Локальный администратор'
export MMM_AUTH_COOKIE_SECURE=false
```

For the research-pilot HTTPS profile, set `MMM_AUTH_COOKIE_SECURE=true`.

## 2. Create the administrator once

```bash
python -B 04_Web_app/backend_runtime.py \
  --config 04_Web_app/config/local_backend_v1.json \
  --bootstrap-admin
```

Expected sanitized result contains `status`, opaque `user_id` and `updated`.
It does not echo email, password, hash or session secret.

Running the command again does not overwrite the existing account. Recovery
or deliberate credential replacement requires the explicit flag:

```bash
python -B 04_Web_app/backend_runtime.py \
  --config 04_Web_app/config/local_backend_v1.json \
  --bootstrap-admin \
  --bootstrap-update-existing
```

That operation revokes the user's sessions and writes an audit event.

## 3. Remove temporary bootstrap values

```bash
unset MMM_AUTH_BOOTSTRAP_ADMIN_EMAIL
unset MMM_AUTH_BOOTSTRAP_ADMIN_PASSWORD
unset MMM_AUTH_BOOTSTRAP_ADMIN_NAME
```

Keep `MMM_AUTH_SESSION_SECRET` available to the running backend through an
untracked local environment or a server secret manager. Changing it invalidates
all existing session cookies because their stored digests can no longer match.

## 4. Start and verify

Start the backend normally, open the browser login page, then verify that
`GET /api/v1/auth/session` returns `authenticated=true` after login. Do not use
the public health endpoint as proof that authentication itself works.
