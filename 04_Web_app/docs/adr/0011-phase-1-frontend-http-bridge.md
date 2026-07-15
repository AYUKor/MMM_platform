# ADR 0011: Phase 1 frontend HTTP bridge

Status: accepted for local pre-production testing on 2026-07-15.

## Context

Frontend Phase 1 was merged into `main` with a contract-backed Result Overview
page and a development-only fixture provider. The page intentionally contained
no optimizer or MMM calculations, but it could not yet read a real completed
job from the local backend. The frontend dev server uses port `4173`, while the
backend localhost CORS allowlist originally covered only port `5173`.

## Decision

1. Preserve all Phase 1 visual components and presentation logic unchanged.
2. Add an HTTP `ResultProvider` that reads
   `GET /api/v1/jobs/{job_id}/result` and returns `decision_result_v1`.
3. Keep fixture mode development-only for isolated UI work.
4. Fail closed when the result is missing, not ready, or has an unknown shape.
5. Allow the actual frontend localhost origins on port `4173` in the local
   backend configuration.
6. Treat the route parameter in
   `/calculations/{id}/result` as `job_id` for this local integration stage.

## Why DecisionResult remains the Phase 1 input

Phase 1 was implemented and tested against `decision_result_v1`. Replacing it
with a second browser contract in the same integration change would modify the
approved frontend presentation layer and increase regression risk. The backend
continues to expose `result_overview_v1` as an additional compact endpoint for
future screens, while the existing Result Overview page consumes the contract
it was built against.

## Consequences

- A completed real optimizer job can be opened at
  `/calculations/{job_id}/result` without fixture data.
- The browser still performs no model, optimizer, reliability, or allocation
  calculations.
- Authentication, shared persistence, enterprise queueing, object storage, and
  deployment remain outside this local pre-production bridge.
