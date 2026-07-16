# Frontend Job Result V1

Status: Frontend Phase C implementation and local acceptance are complete.
GitHub CI status is tracked in the Pull Request.

Backend baseline: `591193f433e5eb3f80f924539bd09cd1c27e50ef`

## Scope

Route `/calculations/{job_id}/result` is the product result workspace for one
completed MMM calculation. It has exactly four tabs:

1. `Обзор`;
2. `Сценарии и надежность`;
3. `Медиаплан`;
4. `Отчет`.

The frontend reads only these result resources:

- `GET /api/v1/jobs/{job_id}/result-view`;
- `GET /api/v1/jobs/{job_id}/media-plan` with the supported scenario,
  pagination and exact channel/geo filters;
- the artifact download path published for the ready marketer workbook.

The new page does not read legacy `GET .../result`, `GET .../overview`, raw
progress, job events, optimizer files, registry files or local artifacts. It
does not call lifecycle job/error endpoints to reconstruct result state.

## Contract boundary

Generated TypeScript types come from `job_result_view_v1` and
`scenario_media_plan_v1`. Runtime responses are still treated as untrusted and
pass fail-closed validation before rendering.

The result parser checks, among other invariants:

- exact contract name and version;
- exact object keys and supported enum values;
- route `job_id` equality and opaque identifiers;
- one campaign and exact S01-S06 order;
- canonical recommendation consistency;
- distinct canonical recommendation, best-safe and best-raw semantics;
- unique safe/raw ranks where values are present;
- `P10 <= P50 <= P90` and the difference between missing and numeric zero;
- requested, allocated and unallocated budget reconciliation;
- channel, geo and geo-channel aggregate reconciliation;
- qualitative reliability components without a reconstructed score;
- report status, workbook media type and artifact metadata;
- download path shape and artifact-ID equality;
- controlled unavailable map, daily-plan and working-XLSX structures;
- absence of workstation paths and unsafe absolute URLs.

The media-plan parser additionally verifies:

- requested scenario, filters, page and page size against the response;
- result/job/campaign identity;
- fixed `segment x geo x channel` total-period grain;
- stable page metadata and filtered/global totals;
- row scenario and filter consistency;
- backend-provided channel, geo and geo-channel aggregates;
- source artifact identity and SHA-256 shape;
- unavailable date matrix, map and working media-plan workbook.

Malformed, future or internally inconsistent responses are not partially
rendered. They produce a controlled unsupported-contract state.

## URL state

The selected tab is stored in the URL:

- `?tab=overview`;
- `?tab=scenarios`;
- `?tab=media-plan`;
- `?tab=report`.

The media-plan scenario is also URL-backed:

`?tab=media-plan&scenario=S05`

Refresh, deep link, browser Back and Forward must restore the same product
view. Unknown tab/scenario values are normalized to a supported view and are
never interpreted as a recommendation.

## Recommendation, S1 and S5

The frontend preserves the recommendation exactly as published by
`result-view`:

- `recommended` shows the canonical scenario and backend display text;
- `no_safe_recommendation` explicitly says that a safe automatic
  recommendation was not formed;
- `unavailable` is a controlled unavailable state.

S1 is always presented as `Исходный план` / `Как загружено`.

S5 is always presented as `Устойчивый ориентир`.

S1 and S5 remain visible even when one of them is also the canonical
recommendation. Duplicate scenario cards are removed, while all applicable
badges remain. In a no-safe state S1 is only the source plan and S5 is only the
stability reference; neither becomes a synthetic winner.

An allocation recommendation concerns redistribution of the submitted budget.
It is not a decision to launch, cancel or approve a campaign.

## Tab: Overview

The campaign header uses only `result-view.campaign`: campaign name, segments,
period, total budget, channel count, geography count and model coverage.
Report download is visible only when the report artifact is ready.

The overview contains:

- canonical recommendation/no-safe/unavailable hero;
- S1 and S5 anchor scenarios;
- direct P10/P50/P90 metrics for the selected product view;
- explicit diagnostic labels for orders metrics;
- requested, allocated and unallocated budgets;
- scenario interval chart with a presentation-only metric selector;
- six qualitative reliability components;
- backend-provided channel and geo comparisons;
- browser-safe warnings;
- a controlled unavailable map panel.

`avg_basket_delta_rub` is not reconstructed and is shown as unavailable.
`avg_basket_turnover_bridge_rub` is labelled as a contribution of the
average-basket mechanism to incremental turnover, never as average-basket
change.

## Tab: Scenarios and reliability

All six scenarios remain in contract order. Each scenario uses only published
fields for:

- title, description and role;
- completion and quality status;
- canonical recommendation, best-safe and best-raw markers;
- safe/raw ranks;
- requested, allocated and unallocated budget;
- available metric P10/P50/P90 values;
- qualitative reliability evidence.

Missing metric or rank values render as `Нет данных`. Numeric zero remains a
real visible value.

The reliability score is currently `null`; the page does not show `0/10` and
does not derive a score from warnings. It shows the six contract components:
historical support, model support, extrapolation, estimate uncertainty,
business constraints and calculated-budget completeness.

Best raw is shown only when `best_raw.available=true`, under the title
`Математически сильный, но не рекомендованный вариант`. Its reason, ranks,
metrics and browser-safe blocking cells are audit evidence only and never
replace the canonical recommendation.

## Tab: Media plan

The control is labelled `Показать медиаплан сценария`. It changes only which
already-calculated plan is displayed.

Default view selection is:

1. canonical recommendation when its media plan is completed;
2. otherwise completed S5;
3. otherwise completed S1.

This fallback is presentation state only. It does not modify recommendation,
best-safe, best-raw, ranks or calculation output.

The media-plan request uses the selected scenario and server-side exact
channel/geo filters, page and page size. The page displays:

- global requested/source/selected/unallocated totals;
- filtered totals from the response;
- backend channel, geo and geo-channel aggregates;
- geo-channel matrix/heatmap data from the response;
- paginated `segment x geo x channel` rows;
- source budget, selected budget, RUB/percent delta and quality status.

The frontend does not sum page rows into source-of-truth totals. A valid filter
with no rows is an honest empty state, not an error. HTTP 422 is contained
inside the media-plan tab so the immutable result remains available.

## Tab: Report

For `ready`, the page shows the actual workbook name, size, generated time when
available, and the published sheet names/descriptions. Download uses only the
validated artifact path.

For `failed`, the page shows backend display text without a fabricated retry
action. For `unavailable`, it renders a controlled unavailable state.

The current backend publishes the separate working media-plan XLSX as
unavailable. The frontend keeps that controlled state, but also renders a
validated download when the existing v1 `ready` artifact state is published. A
CSV is never presented as Excel.

## Loading, errors and recovery

Initial states are distinct:

- loading skeleton;
- 404: `Результат не найден`;
- 409: `Данные временно не согласованы`;
- 503: `Результат временно недоступен`;
- network/request failure;
- unsupported contract.

After one successful `result-view`, a temporary refresh error keeps the last
validated snapshot visible and shows a retry notice. It does not replace data
with zeroes or clear the page. The media-plan query has independent loading,
empty, 422, unavailable and retry states.

## Synthetic review data

Synthetic payloads are allowed only in unit tests, E2E tests and review
screenshots. They use `record_origin=sanitized_fixture` and every rendered
review screen must show the badge `Демонстрационные данные`.

There is no production fixture fallback for the Phase C route. Synthetic PNGs
are visual-review artifacts only; they are not model-quality or business-effect
evidence.

## Controlled unavailable data

The current backend result deliberately keeps these values unavailable:

- numeric reliability score 1-10;
- average-basket delta in RUB/order;
- scenario daily rows;
- channel-by-date matrix/calendar;
- approved map coordinates and Russia projection;
- separate working media-plan XLSX (the v1 schema still defines a validated
  `ready` artifact state for future publication).

The frontend does not geocode names, draw a pseudo-map, distribute total-period
budgets across dates, infer missing values or calculate a reliability policy.

## Documentation truth notes

Two non-blocking stale-document conflicts were explicitly accepted by the user
for this focused Phase C implementation:

1. `PROJECT_BRIEF.md` still describes Frontend Phase B progress integration as
   a future milestone although PR #16 is merged.
2. `CURRENT_TRUTH.md` references nonexistent
   `frontend/src/pages/CalculationProgressPage.tsx`; the implemented file is
   `frontend/src/pages/JobProgressPage.tsx`.

These documents are intentionally not edited in Phase C. Their cleanup belongs
to a separate truth-freeze/documentation milestone and does not change the
accepted Phase C result contracts.

## Verification status

Local verification against baseline
`591193f433e5eb3f80f924539bd09cd1c27e50ef` is complete:

- generated contract types: deterministic, eight generated files, no drift on
  a second generation pass;
- TypeScript: passed;
- ESLint: passed with zero warnings;
- unit tests: 284 passed in 24 files;
- production build: passed;
- Phase C Playwright: 36 passed;
- full frontend Playwright regression: 110 passed;
- visual review: 16 light/dark PNGs, each `1440 x 900`, manually inspected;
- live no-interception acceptance: passed with completed
  `application_runtime` job `job_484bd2e6480ba82c30cf`;
- real report artifact: downloaded as a valid 12,887-byte XLSX with SHA-256
  `25c909f212754e3828880b5ad647cc6bea75cd47ef6172223d57b1b86ac33500`;
- browser network review: zero legacy `/result` and `/overview` requests;
- browser console: zero application errors or warnings;
- responsive review: zero document overflow on desktop, mobile `375 x 812`
  and landscape `812 x 375`.

The live job was created earlier from the synthetic acceptance input
`progress_acceptance.csv`. Its runtime contracts, HTTP flow and artifact
download are real, but its calculation values are not model-quality or
business-effect evidence.

The production build emits Vite's advisory warning for a 530.58 kB minified
JavaScript chunk. The build succeeds; route-level code splitting remains a
separate performance follow-up rather than a Phase C contract or correctness
blocker.

Final evidence belongs in
`04_Web_app/docs/ui-review/job-result-v1/REVIEW_NOTES.md`.

Python backend, schemas, OpenAPI, worker, MMM, forecast, optimizer, Scenario 6
ranking, recommendation policy and report generation are outside Frontend
Phase C.
