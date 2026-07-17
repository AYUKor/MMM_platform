# Backend Phase E.1A: turnover serving and scenario semantics

Status: implemented and locally verified on 2026-07-17.

Baseline: `origin/main@7d731843d6e79fb73b20ac855fba3643b8def7a7` after merged PR #22.

This phase changes the application-serving boundary and optimizer semantics.
It does not retrain the MMM, change posterior response mathematics, alter the
frontend, or provision deployment infrastructure.

## Why this change exists

The research model package contains three target families for four segments:
12 posterior fits in total. Only incremental turnover is sufficiently suitable
for the product decision shown to a marketer. Orders remain difficult to
identify from aggregate media variation, while the average-basket result is a
derived diagnostic bridge rather than an independently optimized business KPI.

The application therefore uses a narrower serving policy than the research
package:

```text
research package: 3 targets x 4 segments = 12 fits
application serving: turnover x 4 segments = 4 fits
```

The eight diagnostic research fits are not deleted. They remain available for
offline model analysis, but new application jobs do not request, calculate, or
publish them as primary result metrics.

## Runtime flow

For a new application job the calculation path is now:

1. parse and normalize one campaign plan;
2. validate file structure separately from model limitations;
3. build daily flighting and reconcile the complete requested budget;
4. request only `turnover_per_user` from the posterior engine;
5. calculate S1-S4 benchmarks;
6. construct the one public S5 using the conservative full-or-partial policy;
7. run S6 only when a full-budget plan is feasible inside approved limits;
8. publish a turnover-only v2 browser projection and marketer report.

`serving_semantics.py` is the shared boundary for the serving target and the
versioned channel catalog. The model package remains the source of posterior,
capability, support, gate, scaling, denominator and adstock truth.

## Additive contract migration

Existing v1 result, validation and model endpoints remain compatible. They are
not silently redefined because already completed jobs and the merged frontend
still depend on them.

New browser-safe projections are additive:

| Endpoint | Contract | Purpose |
|---|---|---|
| `GET /api/v1/jobs/{job_id}/result-view-v2` | `job_result_view_v2` | Turnover-only scenarios, budget/ROAS denominators, risk shares and recommendation semantics. |
| `GET /api/v1/jobs/{job_id}/media-plan-v2` | `scenario_media_plan_v2` | Paginated scenario allocations with stable geo/channel identities and approved display names. |
| `GET /api/v1/validations/{validation_id}/view-v2` | `validation_result_v2` | Separate file validation, grouped turnover limitations and all structured geographies. |
| `GET /api/v1/models/active-v2` | `model_passport_v2` | One serving target and four active serving models. |
| `GET /api/v1/model/overview-v2` | `model_overview_v2` | Turnover-only product model summary. |
| `GET /api/v1/meta/geo-catalog` | `geo_catalog_v1` | Canonical geo identities and honest coordinate availability. |
| `GET /api/v1/workspace/geo-budget` | `workspace_geo_budget_v1` | Reconciled workspace budget by geography for a future map. |

OpenAPI is advanced additively from `1.6.0` to `1.7.0`. JSON Schemas, Python
semantic validators and generated TypeScript types are committed together.
The frontend can migrate screen by screen. New product work must prefer v2;
v1 remains a compatibility surface until its consumers are migrated and a
separate removal decision is approved.

## Scenario semantics

### S1: uploaded plan

S1 is a source benchmark, not an automatic recommendation. It always uses:

```text
scenario_kind = uploaded_plan
scenario_variant = uploaded_plan
decision_status = keep_uploaded_plan
review_status = manual_review_required
is_recommended = false
```

When no safe full reallocation exists, the result-level recommendation may
point to S1 only as the retained reference plan. The browser copy explicitly
says that this is not approval to launch the campaign.

### S5: one public conservative scenario

Only one S5 is published. Internally the optimizer evaluates the following
sequence:

1. try a full allocation inside historical p95 support;
2. if needed, allow controlled expansion to p99;
3. if needed, allow controlled expansion to the approved robust upper bound;
4. if a full allocation is still impossible, publish the maximum allocatable
   robust-bound plan as `safe_partial` and expose the exact remainder.

A feasible full plan is published as:

```text
scenario_variant = full_conservative
allocated_budget_rub = requested_budget_rub
```

The fallback is published as:

```text
scenario_variant = safe_partial
decision_status = no_safe_recommendation
review_status = manual_review_required
```

The full-plan objective is lexicographic: high-risk budget first, then
controlled extrapolation, concentration, distance from the uploaded plan and
only then expected incremental turnover. S5 does not move the complete budget
into one apparently efficient channel merely because its posterior p50 is
large.

### S6: full effect-maximizing plan or infeasible

S6 maximizes incremental turnover under the approved support and gate limits.
Candidate generation checks full-budget capacity before posterior scoring.

S6 has only two legal public outcomes:

- a complete plan with `allocated_budget_rub = requested_budget_rub`;
- `status = infeasible`, zero allocated budget, null effect/ROAS and explicit
  limiting constraints.

A partial S6 is rejected. A raw high-effect candidate outside the policy can
remain audit evidence, but cannot become the recommendation.

Cells whose gate policy fixes spend at the uploaded-plan level do not bypass
the approved support boundary. If a fixed source amount is above that boundary,
S5 may contract it only in the explicit `safe_partial` fallback; S6 treats the
full allocation as infeasible. This prevents a diagnostic or otherwise locked
cell from turning a risky plan into a falsely labelled conservative plan.

## Budget, ROAS and risk invariants

Every scenario publishes:

```text
requested_budget_rub
allocated_budget_rub
unallocated_budget_rub
allocation_share
```

The invariant is:

```text
requested = allocated + unallocated
allocation_share = allocated / requested
```

ROAS is published twice because a partial plan has two legitimate questions:

- `allocated_budget`: effect divided by money actually placed by the plan;
- `requested_budget`: the same effect divided by the marketer's full requested
  budget, including the unallocated remainder.

The primary denominator kind and denominator amount are explicit. For a full
plan the two ROAS values are equal. For unavailable S6 they are null, not zero.

Allocated money is also decomposed into mutually exclusive risk tranches:

```text
within historical support
controlled extrapolation
high risk
```

Their RUB amounts reconcile to allocated budget and their shares reconcile to
one whenever allocated budget is positive. High-risk money cannot be hidden by
a generic model-coverage percentage.

## Validation and catalog semantics

`validation_result_v2` separates two different questions:

- `file_validation`: whether the uploaded rows, campaign count, dates and
  budget can form a job;
- `model_limitations`: where the turnover estimate has caution, diagnostic or
  unsupported policy restrictions.

Orders and average-basket warnings are not copied into this turnover-only
projection. Duplicate model cells are grouped by target, channel and
limitation type with a structured list of all affected geographies.

Machine channel IDs remain stable while browser labels come from
`channel_catalog_v1`:

| `channel_id` | `channel_display_name` |
|---|---|
| `Digital_Performance` | `Цифровая реклама` |
| `OOH_Total` | `Наружная реклама` |
| `Радио` | `Радио` |
| `Indoor` | `Indoor` |

Unknown channel IDs fail closed. Presentation text cannot contain the raw
technical IDs for Digital or OOH.

Geo arrays are built from normalized plan rows and scenario allocations, never
from shortened display strings. Any machine-readable value containing
`... еще N` is rejected. Stable geo IDs are deterministic identities, not map
coordinates.

`geo_catalog_v1` accepts only reviewed canonical coordinates. When none are
available, latitude and longitude remain null and the map state is explicitly
`unavailable`. There is no request-time geocoding or guessed city point.

## Real campaign acceptance

The exact `campaign-plan-example-regions-2026.xlsx` input was accepted against
the current preprod serving package without MCMC refit.

Input reconciliation:

| Check | Result |
|---|---:|
| Source rows | 45 |
| Campaigns | 1 |
| Geographies | 15 |
| Channels | 3 |
| Requested budget | 267,818,706 RUB |
| Parse issues | 0 |
| Blocking file errors | 0 |
| Normalized budget difference | 0 RUB |
| Daily flighting rows | 4,770 |

File validation passed and job creation remained allowed. The turnover-only
model projection grouped one caution limitation for `Цифровая реклама`
affecting all 15 geographies. Orders and average-basket limitations were absent.

Scenario acceptance, rounded here only for documentation:

| Scenario | Variant/status | Allocated, RUB | Unallocated, RUB | Incremental turnover p10/p50/p90, RUB | ROAS allocated/requested p50 | High-risk share |
|---|---|---:|---:|---|---|---:|
| S1 | uploaded plan | 267,818,706 | 0 | 324,744,794 / 345,026,875 / 361,992,820 | 1.288 / 1.288 | 38.17% |
| S2 | full benchmark | 267,818,706 | 0 | 705,120,757 / 749,276,265 / 791,947,700 | 2.798 / 2.798 | 51.94% |
| S3 | full benchmark | 267,818,706 | 0 | 301,871,266 / 319,549,232 / 334,672,776 | 1.193 / 1.193 | 54.14% |
| S4 | full benchmark | 267,818,706 | 0 | 890,070,165 / 944,243,487 / 998,095,411 | 3.526 / 3.526 | 41.49% |
| S5 | `safe_partial` | 173,912,511 | 93,906,195 | 324,148,860 / 344,649,269 / 361,412,312 | 1.982 / 1.287 | 0% |
| S6 | `infeasible` | 0 | 267,818,706 | unavailable | unavailable | unavailable |

The large S2/S4 p50 values are not recommendations: both plans put substantial
money above the approved risk boundary. The conservative full plan was
mathematically impossible for this campaign. S5 therefore published the exact
safe partial capacity. S6 reported that p99 capacity was about 168.4M RUB and
the approved robust-bound capacity about 173.9M RUB, both below the requested
267.8M RUB. No fake full-budget optimizer plan was created.

The result-level decision was:

```text
decision_status = keep_uploaded_plan
review_status = manual_review_required
scenario_id = S01
```

All 15 geographies and all three channels were present in the result. S1-S5
each produced 45 total-period `scenario_media_plan_v2` rows with stable geo IDs
and the labels `Цифровая реклама`, `Наружная реклама` and `Радио`; S6 correctly
had no media plan.
The primary v2 JSON contained no orders, average-basket metric or truncated geo
string. Fifteen geo identities were published with unavailable coordinates.

## Performance evidence

The earlier application run of the same campaign and the turnover-only
acceptance used the same 2,048 Scenario 6 search budget, 128 search draws and
600 finalist draws.

| Measurement | Before | After |
|---|---:|---:|
| End-to-end optimizer runtime | 60.117 s | 42.653 s, 43.733 s and 45.449 s; median 43.733 s |
| Relative observed median reduction | - | 27.3% |
| Posterior fit passes for this one-segment job | 5 | 2 |
| Scenario evaluations in the new run | not instrumented | 11 |

The 27.3% value is an observed median end-to-end comparison, not a pure causal
benchmark of target removal: E.1A also moves the S6 capacity gate before
posterior-kernel construction, and this campaign fails that gate. The pass
count includes the old adaptive kernel pass, search scoring and three-target
finalist scoring (`5`), versus turnover-only search and finalist scoring after
the early gate (`2`). Peak-memory change could not be measured reliably in the
restricted local runtime, so no memory claim is made.

## Verification

Local checks completed:

- 143 backend/web tests passed, 11 external-artifact skips;
- 85 MMM core tests passed, 2 external-fixture skips;
- 392 frontend unit tests passed;
- TypeScript typecheck passed;
- ESLint passed;
- production frontend build passed;
- generated TypeScript contracts were regenerated deterministically.

An independent code review was closed before publication. It additionally
verified published OpenAPI schema references, measured the 12-to-4 model
inventory from package metadata, added the v2 media-plan projection, prevented
fixed cells from bypassing support caps, strengthened coordinate/path/model
schema validation and made the partial-plan business hurdle use requested-
budget ROAS.

## Known limitations

- The research package still has no sealed OOT period and remains
  `preprod_restricted`; E.1A does not change that model-quality fact.
- The current local registry registration contains a stale workstation-relative
  package location. Real acceptance therefore verified the same immutable
  package directly in `serving_bundle` mode. Registry relocation must be fixed
  before a clean server install.
- S5/S6 use historical support capacity, not approved media inventory or
  contractual minima/maxima. Those business constraints remain an open policy
  decision.
- The geo catalog has identities but no reviewed coordinate dataset, so map
  rendering must remain unavailable.
- Legacy v1 contracts remain accessible until frontend consumers migrate; new
  turnover-only screens must use v2 rather than infer new semantics from v1.
