# ADR 0014: Product API v1.1 And Research Pilot

- Status: Accepted
- Date: 2026-07-15
- Scope: browser contract, model passport, readiness, research deployment profile and local retention

## Context

The local marketer flow already proves upload, validation, asynchronous MMM
execution, ResultOverview and Excel download. The next frontend phase needs a
stable discovery boundary: it must know whether the backend is ready, which
model package serves calculations, which `segment x channel x target` cells
are primary/caution/diagnostic, how to page calculation history and how to
interpret HTTP failures.

The project owner selected a research-pilot product, not a formal corporate
production launch. Sealed OOT is currently impossible because a complete new
data period is unavailable. No commercial hurdle is approved, so the product
remains allocation-only and must not issue launch/cancel verdicts.

## Decision

### Product API

The stdlib HTTP application publishes an additive Product API v1.1 boundary:

- `GET /health`: process liveness and enabled capabilities;
- `GET /ready`: serving dependency readiness;
- `GET /api/v1/openapi.json`: route-level OpenAPI 3.1 document;
- `GET /api/v1/contracts/{name}.json`: published JSON Schemas;
- `GET /api/v1/meta/errors`: stable error codes, retryability and user action;
- `GET /api/v1/models/active`: path-safe `ModelPassport v1`;
- `GET /api/v1/jobs?limit=&offset=&status=`: deterministic paginated history.

Existing lifecycle, DecisionResult, ResultOverview and artifact routes remain
authoritative. The API layer contains no adstock, saturation, posterior,
support or optimizer mathematics.

### Model Passport

Preflight resolves and verifies the pinned registry package before the server
starts. The passport is built only from that verified record and immutable
package artifacts. It exposes:

- package ID, fingerprint, stage and activation status;
- training and development-shadow periods;
- segment, channel, geography and target coverage;
- exact policy at `segment x channel x target` grain;
- historical replay and sealed OOT status;
- business-readable caveats.

Target grain is mandatory. A diagnostic `orders_per_user` row must not make a
primary `turnover_per_user` row appear diagnostic. The passport states
`production_claim_allowed=false`; `preprod_restricted` is never relabeled as
production-ready.

### Deployment Profiles

Two configuration profiles share the same domain contracts:

- `local_development`: localhost frontend and backend, `local_only` access;
- `research_pilot`: public HTTPS origin behind a reverse proxy with basic-auth
  or token access control.

The Python server binds only to `127.0.0.1` in both profiles. It is never
exposed directly to the internet. A future server installation terminates TLS
and authenticates users at the reverse proxy, then forwards requests to the
loopback backend. Tracked configs contain no credentials.

### State And Retention

Research-pilot state remains file-backed for the first deployment. A versioned
retention command produces a dry-run plan and can delete only fully expired,
terminal resource families. A validation is deleted only after all related
jobs are eligible; an upload is deleted only after all related validations are
eligible. Resource IDs are validated before deletion, active work is retained,
idempotency indices are pruned atomically and every applied cleanup writes an
audit event.

## Consequences

Frontend and backend can evolve independently against published schemas. A
single-VM research deployment no longer requires PostgreSQL or object storage
before product testing, but it still requires HTTPS, access control, disk
backup/monitoring and a scheduled retention command. File-backed state and a
single worker are not a multi-node or company-contour architecture.

Sealed OOT, commercial thresholds and contractual media constraints remain
visible caveats. They do not block research-pilot forecasting and allocation,
but they continue to block production-model claims, launch/cancel decisions
and operational media-plan approval.

## Validation

Source-only tests cover schema and semantic validation, target-specific model
policy, error catalog, pagination, environment/profile guards, safe retention,
readiness and live loopback routes. A read-only preflight against the current
`preprod` registry package verifies its inventory and builds a schema-valid
passport without exposing workstation paths.
