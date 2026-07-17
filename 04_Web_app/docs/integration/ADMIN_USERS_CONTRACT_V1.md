# Admin Users Contract v1

## Purpose

These endpoints manage only local research-pilot accounts. They do not manage
company identities and do not emulate SSO.

## Endpoints

| Method | Route | Permission |
|---|---|---|
| `GET` | `/api/v1/admin/users` | `admin.users.read` |
| `POST` | `/api/v1/admin/users` | `admin.users.write` + `admin.roles.write` |
| `GET` | `/api/v1/admin/users/{user_id}` | `admin.users.read` |
| `PATCH` | `/api/v1/admin/users/{user_id}` | field-specific; see below |
| `POST` | `/api/v1/admin/users/{user_id}/disable` | `admin.users.write` |
| `POST` | `/api/v1/admin/users/{user_id}/enable` | `admin.users.write` |
| `POST` | `/api/v1/admin/users/{user_id}/sessions/revoke` | `admin.sessions.write` |
| `GET` | `/api/v1/admin/roles` | `admin.users.read` |

List filters are `page`, `page_size`, `search`, `role`, `status` and `sort`.
Sorting values are `created_desc`, `created_asc`, `name_asc`, `email_asc` and
`last_login_desc`. Unknown or duplicated parameters fail closed with
`ADMIN_QUERY_INVALID`.

Create requires `email`, `display_name`, `password` and `role_id`. PATCH accepts
only `display_name` and/or `role_id`; password reset is deliberately absent.

Mutation permissions are enforced by the backend service, not inferred by the
frontend:

- `display_name`, enable and disable require `admin.users.write`;
- assigning `role_id` during create requires both `admin.users.write` and
  `admin.roles.write`;
- changing `role_id` through PATCH additionally requires
  `admin.roles.write`;
- session revoke requires `admin.sessions.write`.

Therefore a custom permission bundle with `admin.users.write` but without
`admin.roles.write` may maintain profile/status fields but receives `403` for
role assignment. No additional production role is introduced.

## Invariants

- normalized email is unique;
- the last active administrator cannot be disabled or downgraded;
- self-disable is prohibited;
- disabling a user atomically revokes all of that user's sessions;
- every mutation creates an append-only audit event;
- password and password hash never appear in user responses or audit events.

`admin_role_catalog_v1` contains both role bundles and the complete versioned
permission catalog. Frontend must display or hide actions from the current
session permissions, not from hardcoded role assumptions.
