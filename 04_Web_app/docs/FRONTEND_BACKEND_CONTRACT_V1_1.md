# Frontend Handoff: Backend Product API v1.6

## What Is Stable

The browser orchestrates resources and renders returned contracts. It must not
recalculate MMM metrics, join optimizer CSV files, rank scenarios or infer a
different recommendation.

Stable result contracts:

- `DecisionResult v1`: full completed-job audit result;
- `ResultOverview v1`: compact browser result projection;
- `ModelPassport v1`: active model coverage and reliability policy;
- application lifecycle v1: upload, validation, job, progress and errors;
- `JobProgressView v1`: browser-safe nine-stage calculation snapshot;
- `MmmFactCatalog v1`: reviewed static progress-screen facts;
- `JobList v1`: paginated calculation history.
- `AuthSession v1`: current user, server-side session metadata and authoritative permissions;
- `AdminUserList/Detail v1`, `AdminRoleCatalog v1`,
  `AdminSystemStatus v1`, `AdminAuditLog v1`: Phase E administration.

## Authentication Boundary

Only liveness, readiness, login and session check are anonymous. Every other
product route is protected by a centralized backend permission map.

1. Call `GET /api/v1/auth/session` when the application starts.
2. If anonymous, submit credentials to `POST /api/v1/auth/login`.
3. Send later requests with browser credentials enabled; JavaScript never
   receives or persists the opaque HttpOnly token.
4. Render capabilities from `session.user.permissions`, not from `role_id`.
5. Treat `401` as missing/expired authentication and `403` as a valid session
   without the requested permission.
6. Use `POST /api/v1/auth/logout` to revoke the server-side session.

All POST/PATCH requests must originate from an allowed browser origin. The
backend validates both Origin and Host.

## Discovery Endpoints

| Method and route | Frontend use |
|---|---|
| `GET /health` | Is the HTTP process alive? |
| `GET /ready` | Are package, campaign service and local stores ready? |
| `GET /api/v1/models/active` | Show model period, coverage and caveats. |
| `GET /api/v1/meta/errors` | Map stable error codes to user actions. |
| `GET /api/v1/meta/mmm-facts` | Load reviewed optional MMM facts without live generation. |
| `GET /api/v1/openapi.json` | Machine-readable route specification. |
| `GET /api/v1/contracts/product-api-v1.json` | Model passport, error catalog and job-list schema. |
| `GET /api/v1/contracts/application-lifecycle-v1.json` | Upload/validation/job schema. |
| `GET /api/v1/contracts/decision-result-v1.json` | Full result schema. |
| `GET /api/v1/contracts/result-overview-v1.json` | Compact result schema. |
| `GET /api/v1/contracts/job-progress-view-v1.json` | Nine-stage progress snapshot schema. |
| `GET /api/v1/contracts/mmm-fact-catalog-v1.json` | Static MMM facts schema. |
| `GET /api/v1/contracts/auth-session-v1.json` | Current session schema. |
| `GET /api/v1/contracts/admin-user-list-v1.json` | Admin user list schema. |
| `GET /api/v1/contracts/admin-user-detail-v1.json` | Admin user detail schema. |
| `GET /api/v1/contracts/admin-role-catalog-v1.json` | Role and permission catalog schema. |
| `GET /api/v1/contracts/admin-system-status-v1.json` | Safe subsystem checks schema. |
| `GET /api/v1/contracts/admin-audit-log-v1.json` | Append-only audit page schema. |

## Administration

The admin navigation is backed by `/api/v1/admin/users`, `/roles`,
`/system/status` and `/audit`. User list and audit filtering, sorting and
pagination happen on the server. Frontend must not read SQLite, lifecycle
files, runtime cards, environment values or logs directly.

The local account provider is pilot-only. A future corporate provider must
preserve `AuthSession v1` and permissions; the frontend must not contain a
parallel SSO assumption or local role-to-permission table.

## Product Progress

Use `GET /api/v1/jobs/{job_id}/progress-view` for the calculation progress
page. Do not build the UI from raw `/progress` events.

The response always contains P01-P09, one campaign summary, queue state,
Scenario 6 counters, report state, safe errors, cancellation availability and
result availability. `null` counters mean the current worker does not publish
that value; they are not zero. The contract intentionally has no ETA, overall
percentage, temporary Scenario 6 winner or unfinished business metrics.

Poll by `job_id`. Repeated GET requests are read-only. Navigate to the result
only after `job_status.code=succeeded` and `result_available=true`; backend does
not require an automatic redirect.

## Job History

Use `GET /api/v1/jobs?limit=50&offset=0`. Optional `status` values are
`queued`, `running`, `cancel_requested`, `succeeded`, `failed`, `cancelled`
and `timed_out`. The response contains `items`, `total`, `limit`, `offset` and
`next_offset`. An absent `next_offset` means the last page.

## Model Passport Interpretation

- `serving.calculation_allowed=true` means the verified package can serve
  research forecast/allocation jobs. It does not mean formal production.
- `serving.production_claim_allowed` is currently always `false`.
- `validation.sealed_oot.status=unavailable` means complete new-period data is
  not available; show the caveat, but do not disable research calculations.
- `coverage.channel_policies[]` is at exact
  `segment x channel x target` grain. Never collapse all targets to the worst
  status before showing the user which KPI is affected.
- `orders_per_user` may be diagnostic while turnover or average basket remains
  usable. Diagnostic rows cannot drive Scenario 6.
- Model passport caveats describe model use. Campaign-specific support and
  quality warnings still come from ValidationResult and DecisionResult.

## HTTP Errors

Every registered HTTP error contains:

- `code`: stable frontend branch key;
- `display_text`: current user-facing explanation;
- `retryable`: whether retry may help;
- `user_action`: recommended next action.

Frontend logic should branch on `code`, not Russian display text. The complete
catalog is returned by `/api/v1/meta/errors`.

## Environment Boundary

Local development uses `http://127.0.0.1:8765`. A research server will expose
the same routes under one HTTPS origin through a reverse proxy. Frontend code
must use its configured API base URL and must not contain workstation paths,
model folders, registry paths or artifact filesystem paths. Credentialed CORS
is allowed only for configured origins; wildcard origins are invalid.
