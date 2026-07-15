# ADR 0016: Post-Merge Full-Stack Acceptance

Status: Accepted for the local research release-candidate

Date: 2026-07-16

## Context

PR #10 added the Research Pilot Deployment v1 source boundary. PR #11 then
connected the standalone Model Passport page to Product API v1.1. Both were
merged into `main`; the resulting merge commit was
`182e81eb2fd20d992966950687a40abbfe3aa319`.

A combined acceptance was required because separate backend and frontend test
reports do not prove that the merged browser, API, worker and registered model
still operate as one system.

## Acceptance Boundary

The acceptance used an isolated worktree created from the exact `main` commit
above. It installed the previously verified panel-free serving bundle with
SHA-256
`fe974de658fe6916496a9a4c89ca0944d7feef86beb3c856cc0e3c2a61a13ec7`.
Installation reported 58 files and confirmed that the source training panel
was not copied.

Backend preflight resolved:

- registry channel `preprod`;
- package `pkg_807d3ddbae57a52a_9aacd3beb350725b`;
- package fingerprint
  `807d3ddbae57a52ad184f94cd5442cdefd97764fe3903e5b250b5d04cd26c62c`;
- 55 serving-inventory files;
- historical replay `passed`;
- sealed OOT `unavailable`;
- calculation scope `forecast_and_allocation_only`;
- `production_claim_allowed=false`.

This is application and research-calculation evidence. It is not sealed OOT,
production model activation or a launch/cancel business decision.

## Source Verification

The release-candidate passed:

- MMM core: 78 passed, with 2 explicit external-fixture skips;
- web/backend with the installed serving bundle: 57 passed and 9 explicit
  historical optimizer-run fixture skips, 66 discovered tests in total;
- generated TypeScript contract drift check;
- TypeScript typecheck;
- ESLint;
- frontend unit tests: 79/79;
- production frontend build;
- Playwright/Chrome: 14/14.

PR #11 GitHub CI separately performed a clean locked dependency installation
and passed both repository checks. The local acceptance reused the same locked
dependency graph.

## Real Browser And Worker Acceptance

One canonical synthetic smoke campaign was sent to the local upload endpoint.
The browser then loaded the resulting validation record and displayed:

- campaign `deployment_smoke`;
- segment `ТС5/Онлайн`;
- one `МОСКВА x OOH_Total` cell;
- one active day;
- `400,000 RUB` uploaded and model-input budget;
- zero unmodeled budget;
- two non-blocking target-specific warnings.

The browser created immutable job `job_409c15a7af306e5ef9ea`. The real worker
used 2,048 Scenario 6 attempt budget, 128 search posterior draws and 600 final
posterior draws. It completed forecast, benchmark scenarios, result adapters
and marketer reporting.

S1-S5 were identical and reliable because the smoke plan contains only one
budget cell. S6 was explicitly unavailable because there was no second allowed
cell to receive a transfer. The UI did not invent S6 metrics or interpret that
state as a recommendation to cancel the campaign.

The browser rendered overview, Scenarios 1-6, reliability, media plan and
report views. It received an Excel download event. The marketer workbook was
also fetched by opaque artifact ID:

- artifact `artifact_d600032588c98b8e2495`;
- size `12,379` bytes;
- SHA-256
  `d54588551930e0305aac56f553bba13c29836aeb1a14d5eed96815075d75911d`;
- detected file type `Microsoft Excel 2007+`.

## Findings And Fixes

1. `PROJECT_BRIEF.md`, `CURRENT_TRUTH.md` and `PROJECT_HANDOFF.md` still called
   Model Passport an unconnected shell. They are updated to match PR #11.
2. Model Passport target summaries omitted allowed-use categories whose count
   was zero. The browser therefore displayed `Нет данных` where the known
   value was zero. Product API now emits all four categories for every target,
   and a regression assertion covers the projection.
3. Playwright's result tests relied on an ambient
   `VITE_RESULT_PROVIDER=http`. The Playwright web-server config now pins HTTP
   mode, so `test:e2e` is reproducible from a clean shell.
4. The real-package service test relocated a registry registration into a
   temporary evidence root without re-signing that temporary copy. The model
   registry correctly rejected it as mutated metadata. The fixture now keeps
   the original registry immutable, re-signs only its relocated temporary
   registration and channel pointer, selects explicit `serving_bundle`
   verification, and isolates Git cleanliness from job-contract assertions.
   Production registry and clean-source guardrails are unchanged.

No MMM mathematics, optimizer policy, API schema, model package or product UI
component was changed.

## Explicit Limitations

- Native browser file-picker automation was not established. The source file
  was uploaded through the exact HTTP endpoint used by the frontend, and the
  rest of validation, job creation and result navigation was exercised in the
  browser.
- A fresh visual render of the generated workbook was not completed because
  the approved spreadsheet runtime was rejected by macOS native-module code
  signing. Browser download, file type, size and SHA-256 were verified. Earlier
  workbook-render evidence remains separate and is not re-claimed here.
- External VM, domain, TLS and access-control deployment remain infrastructure
  work. This acceptance covers local research-pilot behavior only.

## Decision

Accept the combined local backend/frontend/model path as a release-candidate
for review. Publish these fixes through a pull request. Do not merge directly
to `main` and do not describe the model as production-ready.
