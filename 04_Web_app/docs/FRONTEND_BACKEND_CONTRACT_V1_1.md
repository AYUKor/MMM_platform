# Frontend Handoff: Backend Product API v1.1

## What Is Stable

The browser orchestrates resources and renders returned contracts. It must not
recalculate MMM metrics, join optimizer CSV files, rank scenarios or infer a
different recommendation.

Stable result contracts:

- `DecisionResult v1`: full completed-job audit result;
- `ResultOverview v1`: compact browser result projection;
- `ModelPassport v1`: active model coverage and reliability policy;
- application lifecycle v1: upload, validation, job, progress and errors;
- `JobList v1`: paginated calculation history.

## Discovery Endpoints

| Method and route | Frontend use |
|---|---|
| `GET /health` | Is the HTTP process alive? |
| `GET /ready` | Are package, campaign service and local stores ready? |
| `GET /api/v1/models/active` | Show model period, coverage and caveats. |
| `GET /api/v1/meta/errors` | Map stable error codes to user actions. |
| `GET /api/v1/openapi.json` | Machine-readable route specification. |
| `GET /api/v1/contracts/product-api-v1.json` | Model passport, error catalog and job-list schema. |
| `GET /api/v1/contracts/application-lifecycle-v1.json` | Upload/validation/job schema. |
| `GET /api/v1/contracts/decision-result-v1.json` | Full result schema. |
| `GET /api/v1/contracts/result-overview-v1.json` | Compact result schema. |

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
model folders, registry paths or artifact filesystem paths.
