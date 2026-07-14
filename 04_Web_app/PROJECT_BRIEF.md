# X5 MMM Enterprise Application

## Status

Contract and integration foundation for the future enterprise application. The
folder contains the implemented DecisionResult v1 contract, the adapter from
completed optimizer artifacts, sanitized real-derived fixtures, tests, and the
canonical architecture documents. There is still no execution worker, HTTP
API, database runtime, authentication, or frontend. The previous mock/stub
prototype was removed because it duplicated `mmm_core` and returned synthetic
calculation results.

## Product Purpose

The product is an internal browser-based tool for marketers and media planners. A user uploads a future campaign specification and receives:

1. validation of campaign dates, budget, segment, channels and geographies;
2. an incremental media-effect forecast with p10/p50/p90 uncertainty;
3. five transparent benchmark scenarios;
4. Scenario 6 with support-aware budget optimization across `geo x channel`;
5. a recommended media plan when a reliable automatic recommendation is available;
6. a clear manual-review status when the model can calculate a scenario but cannot safely automate the decision;
7. a marketer-facing Excel report and equivalent browser views.

The application will first run locally for development and then move into the company infrastructure without changing the MMM calculation logic.

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
- Scenario 6 distinguishes `best_raw`, `best_safe` and `no_safe_candidate`.
- The UI never hides warnings, but translates them into business language.
- Production activation remains fail-closed when mandatory model gates are not passed.

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
