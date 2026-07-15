# ADR 0012: Local core marketer flow

Status: accepted for local pre-production testing on 2026-07-15.

## Context

Phase 1 could display a completed DecisionResult, but a marketer still could
not upload a future campaign, review validation, start a calculation, observe
progress, or return to previous jobs from the browser.

## Decision

1. Generate TypeScript lifecycle types from the same Draft 2020-12 schema used
   by the Python backend.
2. Keep upload, validation, and job as separate resources and UI stages.
3. Prevent job creation until validation explicitly returns `valid` and
   `job_creation_allowed=true`.
4. Let the backend choose the approved standard sampling profile. The browser
   does not expose posterior draws or Scenario 6 search budgets to marketers.
5. Read progress from append-only `ProgressEvent v1` records and redirect to
   the result only after job status becomes `succeeded`.
6. Add local `GET /api/v1/jobs` history backed by server state. Each list item
   combines a browser-safe DecisionJob with campaign preview from its immutable
   validation record.
7. Keep calculation, model selection, support policy, optimization, and report
   generation outside React.
8. Persist the completed validation identity in the page URL so refresh and
   recovery reload the server record instead of losing the validation preview.

## Local routes

- `/calculations`: server-side job history;
- `/calculations/new`: upload and validation preview;
- `/calculations/{job_id}/progress`: lifecycle and progress;
- `/calculations/{job_id}/result`: completed DecisionResult.

## Consequences

- The local browser now covers the core marketer path end to end.
- Job history survives a browser refresh because it belongs to backend state,
  not local storage.
- The local list endpoint has no pagination, ownership filtering, or RBAC.
  The enterprise adapter must add those controls while preserving the route
  semantics and lifecycle contracts.
- Standard-profile browser acceptance evidence is recorded in ADR 0013.
