# ADR 0021: turnover-only serving and scenario semantics v1

## Status

Accepted for the research-pilot application boundary.

## Context

The immutable research package contains turnover, orders and average-basket
posterior fits for four segments. Orders are diagnostic-only under the gate
policy, and average basket is not an independent primary optimizer KPI.
Serving all three targets increased runtime and allowed diagnostic metrics to
leak into the primary product result.

The former S5 implementation could return a partial support-safe plan without
making the missing budget explicit enough. The former S6 path could evaluate
allocations that did not satisfy a full-budget decision question. S1 could also
look recommended when the optimizer merely failed to prove a better safe plan.

## Decision

1. Application jobs request only `turnover_per_user` and publish it as target
   ID `turnover`.
2. The research package remains immutable: its 12 fits are retained, while the
   application-serving inventory contains the four turnover fits.
3. Orders, orders-derived metrics and average-basket bridges are absent from
   the new primary result and recommendation logic.
4. One public S5 is built by trying full conservative allocations through
   p95, p99 and the approved robust upper boundary. `safe_partial` is legal
   only after all full options are infeasible and must expose the remainder.
5. S6 is effect-first under approved risk limits and is legal only as a full
   allocation. Otherwise it returns explicit `infeasible` with null metrics.
6. Every scenario publishes reconciled requested, allocated and unallocated
   budgets, both ROAS denominators and mutually exclusive risk-budget shares.
7. S1 is an uploaded-plan reference with manual review; it is never marked as
   an automatically recommended reallocation.
8. New semantics are delivered through additive v2 contracts. Existing v1
   endpoints remain compatible while consumers migrate.
9. The 12-research-fit and four-turnover-fit inventory is measured from model
   package metadata and fails closed when the approved topology is not present.
10. Scenario media plans use an additive v2 projection with canonical geo and
    channel identities; v1 remains readable for existing consumers.
11. A fixed-at-source cell cannot bypass the approved support cap. Contracting
    it is legal only in the explicit S5 partial fallback; S6 remains full or
    infeasible.

## Consequences

- marketer-facing calculations have one primary business effect and lower
  posterior loading cost;
- a large expected effect outside approved support cannot win by hiding its
  risk or denominator;
- partial-budget efficiency can be compared honestly with full-request
  efficiency;
- no scenario can silently drop budget;
- completed historical v1 jobs remain readable;
- frontend migration is required before legacy diagnostic sections disappear
  from all existing screens;
- this decision does not prove causal saturation curves, pass sealed OOT or
  approve a campaign launch threshold.
