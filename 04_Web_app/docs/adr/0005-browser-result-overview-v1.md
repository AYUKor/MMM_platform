# ADR 0005: Browser Result Overview V1

- Status: Accepted
- Date: 2026-07-15
- Scope: browser-facing projection of a verified DecisionResult

## Context

DecisionResult v1 is the canonical completed-job domain result. It is suitable
for audit and worker/API exchange, but it does not directly answer several UI
questions: ROAS uncertainty, the change from uploaded to recommended budget by
`geo x channel`, and why `best_raw` can differ from `best_safe`.

These values must not be reconstructed independently in React, and the web
layer must not read loose CSV files. A stable server projection is therefore
needed between the canonical result and the frontend.

## Decision

`ResultOverview v1` is a read-only presentation contract assembled by
`04_Web_app/adapters/result_overview_adapter.py` after DecisionResult source
hashes and semantics have been verified.

The overview:

- preserves campaign passports, five decision statuses, quality and warnings;
- exposes Scenarios 1-6 in fixed order;
- provides incremental turnover and ROAS p10/p50/p90;
- marks incremental orders as `diagnostic_only`;
- renames the basket total to `avg_basket_turnover_bridge` and preserves its
  explicit turnover-bridge unit;
- compares the selected and uploaded plans by incremental-turnover p50 and
  moved budget;
- provides original, recommended and delta budget for each `segment x geo x
  channel` line;
- represents `best_raw` and `best_safe` separately, with final-posterior versus
  search-only evaluation level, gate eligibility and rejection reasons;
- exposes only opaque candidate IDs;
- converts artifact storage references to canonical API download paths without
  exposing workstation paths.

ROAS p10/p50/p90 is deterministic presentation arithmetic over the same
turnover posterior quantiles and fixed scenario spend. The adapter verifies
that derived p50 reconciles with the canonical source `roas_p50`; it does not
run MMM or optimizer mathematics.

DecisionResult remains the source of truth. ResultOverview is a versioned
projection, not a competing domain result or persistence authority.

## Consequences

- The frontend can render one stable JSON object instead of joining technical
  CSV files or inventing metric semantics.
- Multi-campaign jobs remain one overview with `campaigns[]`; the UI must use a
  campaign selector rather than silently dropping campaigns.
- A gate-blocked Scenario 6 has no invented metrics or candidates.
- The future HTTP layer may cache the overview, but it must be reproducible
  from the immutable completed result evidence.
- Reliability is represented by statuses, support and explanations. No
  synthetic 1-10 reliability score is introduced.

## Validation

The schema and tests cover a sanitized real-derived fixture, a successful safe
Scenario 6, a gate-blocked Scenario 6, a multi-campaign result, ROAS
reconciliation, allocation deltas, opaque IDs and canonical download paths.

