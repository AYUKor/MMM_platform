# Admin Audit Contract v1

`GET /api/v1/admin/audit` requires `admin.audit.read` and returns the paginated
`admin_audit_log_v1` contract.

Supported filters:

- `page`, `page_size`;
- exact `actor_user_id`;
- exact `event_type`;
- `occurred_from_utc`, `occurred_to_utc` with timezone;
- `sort=occurred_desc|occurred_asc`.

Recorded event families are login success/failure, logout, session revoke,
user create/update/enable/disable, role change and admin views of system/audit.
Events are insert-only: SQLite triggers reject update and delete operations.

Failed login events store an HMAC-derived identity label rather than the raw
attempted email. No event contains a password, password hash, session token,
cookie, raw request body, local path or stack trace. `browser_safe_summary` is
reviewed Russian text intended for the admin page.

Reading this endpoint itself records `admin_viewed_audit_log`. That security
side effect is intentional and does not mutate campaign or calculation data.
