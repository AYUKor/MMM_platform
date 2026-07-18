# X5 MMM Enterprise Application

## Status

Working local product foundation and research-pilot backend contract.
The folder contains implemented DecisionResult v1, ResultOverview v1,
application lifecycle v1 and Product API v1 contracts, the completed-result
adapter, local Execution Worker v1, localhost HTTP API, marketer
upload/validation service, model passport, runtime launcher/recovery and
retention, research-pilot deployment tooling, source-only tests, canonical
architecture documents, the browser-safe JobProgressView v1,
JobResultView v1 and ScenarioMediaPlan v1 backend contracts, Phase D
navigation contracts, local pilot authentication/administration, and the
merged Phase D React frontend. The browser includes campaign result,
Scenarios 1-6, reliability, warning, media-plan and report views. The
standalone Model Passport route is connected to
`GET /api/v1/models/active` through a typed, fail-closed client and exposes
training period, coverage, replay/OOT status, channel policy and caveats.
Backend Phase E.1A adds an additive turnover-only serving boundary: new jobs
request one target, the application validates four active turnover fits out of
the 12-fit research package, and v2 result/model/validation/media-plan
contracts remove orders and average-basket metrics from primary product
decisions. S5 now publishes a full conservative plan when feasible or an
explicit partial plan; S6 publishes a full plan or explicit infeasibility.
The merged Phase E.1B frontend consumes those v2 semantics. Backend Phase E.1C
adds a versioned 220-geography static coordinate/alias catalog, server-side
canonical geo aggregation and explicit partial/unavailable map coverage. Map
rendering remains a separate frontend milestone.
Panel-free model transfer, reverse-proxy/systemd rendering, health, retention
and backup/restore are implemented. There is still no provisioned hosted
VM/domain/TLS secret, durable company queue, PostgreSQL runtime, approved
object storage or corporate authentication. The application now has local
research-pilot login, server-side sessions, viewer/analyst/admin permissions
and administrative audit; this is not corporate SSO/MFA. The
previous mock/stub prototype was
removed because it duplicated `mmm_core` and returned synthetic calculation
results.

Backend Phase C adds additive `GET /api/v1/jobs/{job_id}/result-view` and
`GET /api/v1/jobs/{job_id}/media-plan`. They provide canonical recommendation,
S01-S06 metrics, source-backed ranks, backend budget aggregates, hash-checked
report metadata and paginated `geo x channel` scenario plans. The new
projections explicitly keep reliability score, average-basket delta, daily
scenario plans and working-plan XLSX unavailable until real versioned evidence
exists. Phase E.1C now supplies the separate reviewed coordinate evidence.

## Product Purpose

The product is an internal browser-based tool for marketers and media planners. A user uploads a future campaign specification and receives:

1. validation of campaign dates, budget, segment, channels and geographies;
2. an incremental turnover media-effect forecast with p10/p50/p90 uncertainty;
3. five transparent benchmark scenarios;
4. Scenario 6 with support-aware budget optimization across `geo x channel`;
5. a recommended media plan when a reliable automatic recommendation is available;
6. a clear manual-review status when the model can calculate a scenario but cannot safely automate the decision;
7. a marketer-facing Excel report and equivalent browser views.

The application first runs locally and may then move to one external
research-pilot server behind HTTPS and simple access control. A later company
deployment can replace runtime adapters without changing MMM calculation logic
or browser contracts.

The backend has an asynchronous HTTP boundary for immutable jobs, progress
polling, verified results and artifact downloads. Product API OpenAPI v1.8 additionally
publishes readiness, exact model policy, stable HTTP errors, OpenAPI, schemas
and paginated history. Phase B adds a fixed nine-stage `progress-view`, real
Scenario 6 counters where available, a separate report status and a reviewed
static MMM fact catalog. The frontend progress-page integration remains a
separate milestone. The Python process remains loopback-only in both local and
research profiles; a research server must place HTTPS at a reverse proxy and
supply the application session secret through untracked secret handling.

The trained model remains outside Git. A verified serving bundle transfers the
registered model inventory and registry evidence while retaining the training
panel hash as provenance and excluding the panel itself. Model-development
work continues to use full source-lineage checks; the server uses the explicit
`serving_bundle` verification mode.

The local marketer path also accepts a canonical campaign CSV/XLSX, parses and
validates it in the background against the pinned preprod package, then creates
the immutable DecisionJob. Specialized agency workbooks require an explicit
future input profile and are not auto-detected.

`backend_runtime.py` provides a versioned preflight and one-command localhost
launch. Local restart recovery resumes deterministic preparation, requeues
jobs that never started and fails interrupted attempts with a retryable,
auditable error instead of leaving stale `running` state.

The owner-approved current product scope is `research_pilot` and
`allocation_only`. Missing sealed OOT does not block research calculations,
but the package remains `preprod_restricted` and cannot be described as
production-ready. No launch/cancel business verdict is produced.

## User Journey

1. The marketer uploads CSV/XLSX campaign data.
2. The system stores the original file and its SHA-256 hash.
3. The system normalizes the brief into the canonical campaign plan.
4. Blocking validation errors are separated from non-blocking risks.
5. The user confirms the normalized plan and total budget.
6. A background job resolves the active model package through the model registry.
7. Forecast, benchmark scenarios, Scenario 6 and the report are calculated on the server.
8. The user sees job progress and receives a result linked to the exact input, model package, policy version and code version.

## Source Of Truth

The production calculation source of truth remains outside the web layer:

- model lifecycle and registry: `02_Code/01_PyMC`;
- shared campaign preparation and forecast engine: `02_Code/01_PyMC/mmm_core`;
- forecast workflow: `02_Code/03_AC_forecast`;
- optimizer and marketer report: `02_Code/02_Budget_optimizer`;
- immutable model packages and derived outputs: `03_Outputs`.

The web application must call this real backend. It must never copy adstock, saturation, scaling, posterior scoring, gate or optimizer mathematics into a second `mmm_core` implementation.

## Decision Semantics

The product must keep four different questions separate:

1. **Can the input be calculated?** Schema and capability validation.
2. **How much incremental effect does the model estimate?** Forecast p10/p50/p90.
3. **Can the system automatically reallocate budget?** Optimizer feasibility and reliability.
4. **Should the campaign be launched?** A business decision that also needs commercial thresholds and human context.

A support warning must not be translated into a blanket statement that advertising should not run. When the campaign is calculable but contains extrapolation, the correct status is manual review, with the risky channels and geographies shown explicitly.

## Non-Negotiable Architecture Rules

- No notebook execution from the browser.
- No long-running model calculation inside an HTTP request.
- Forecast, optimization and report generation run as background jobs.
- The API and frontend contain no duplicated MMM mathematics.
- Every job is reproducible and linked to input hash, model package ID, package fingerprint, gate policy, configuration, random seed and output hashes.
- The model registry decides which package can serve a job.
- Diagnostic-only targets never drive optimization or campaign go/no-go.
- New application jobs calculate and serve turnover only; diagnostic research
  targets remain outside the primary product result.
- S5 partial budget and S6 infeasibility are always explicit; no scenario may
  silently drop requested budget.
- ROAS always names its denominator, and risk-budget money reconciles to the
  allocated budget.
- Machine-readable geo arrays remain complete and map coordinates are never
  guessed.
- Active turnover-serving geographies must be a subset of the versioned static
  geo catalog; unknown campaign geographies retain their rows and budget with
  null coordinates and explicit partial coverage.
- Registered geo aliases are canonicalized before model support validation;
  package model keys and browser display labels remain separate, auditable
  fields.
- Workspace geo aggregates are built from saved job-backed validations and
  deduplicate repeated validation references before summing budget.
- Scenario 6 distinguishes `best_raw`, `best_safe` and `no_safe_candidate`.
- The UI never hides warnings, but translates them into business language.
- Production activation remains fail-closed when mandatory model gates are not passed.

The merged browser still consumes versioned v1 projections. New result work
must migrate to `job_result_view_v2` for turnover-only scenario semantics.
The canonical completed-job artifacts remain source evidence; React must not
join optimizer CSV files or derive alternative metric, risk, denominator or
recommendation semantics.

## Initial Enterprise MVP

The first usable version should include:

- authenticated campaign upload;
- canonical validation and normalized-plan preview;
- one background job type for the complete `forecast + optimizer + report` workflow;
- job status and progress events;
- scenario comparison and recommended-plan views;
- model quality and support explanation;
- downloadable marketer Excel report;
- audit history by user, campaign, model version and timestamp;
- admin-only model registry status and rollback controls.

Corporate SSO, infrastructure monitoring, backups and production storage adapters are required for company deployment, but they must not alter the domain contracts above.

## Research Pilot MVP

The nearer-term product can use one external VM with local file-backed state,
one worker, a reverse proxy, HTTPS, simple access control, scheduled retention,
disk monitoring and backup. PostgreSQL, object storage, SSO/RBAC and a durable
distributed queue are deferred until usage or company-contour requirements
justify them. This is a deployment simplification, not permission to expose
the stdlib Python server directly to the internet.
