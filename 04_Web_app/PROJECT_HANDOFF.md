# X5 MMM Web Application Handoff

## Purpose

This handoff defines the frozen integration boundary for the future enterprise application. Current package, run, QA, and blocker facts live only in `04_Web_app/CURRENT_TRUTH.md` and must be verified from its cited evidence before implementation.

As of 2026-07-15:

- the verified serving channel is `preprod`;
- that pointer resolves to `pkg_807d3ddbae57a52a_9aacd3beb350725b` with fingerprint `807d3ddbae57a52ad184f94cd5442cdefd97764fe3903e5b250b5d04cd26c62c`;
- the package is `preprod_restricted`, not production-active;
- the latest code-lineage optimizer run is `optimizer_agency_gender_boost_contract_v1_14072026`;
- the current business mode is `allocation_only`;
- DecisionResult v1 and its completed-result adapter are implemented under `04_Web_app`;
- application lifecycle v1 now defines upload, validation, immutable jobs,
  legal transitions, progress, and browser-safe errors;
- local Execution Worker v1 now verifies immutable inputs and package/policy
  pins, launches the existing optimizer/report CLI in a subprocess, publishes
  lifecycle progress, and composes DecisionResult with the original `job_id`;
- localhost HTTP API, canonical upload, model-aware validation, recoverable
  local runtime, ResultOverview delivery, and hash-checked downloads are
  implemented and have passed a real preprod-package E2E job;
- Product API v1.1 now adds readiness, a verified target-grain model passport,
  stable HTTP errors, OpenAPI/JSON Schema discovery, paginated history,
  local/research deployment profiles and safe terminal-resource retention;
- frontend Phase 2 is merged without replacing its design or history; the
  browser covers upload and validation review, immutable job creation,
  progress and cancellation, server-backed history, campaign-level Scenarios
  1-6, reliability and warnings, row-level media-plan comparison, reports and
  Excel download;
- cross-stack pull-request CI now runs both the Python contract suite and a
  locked Node 22 frontend pipeline with generated-contract drift detection,
  TypeScript, ESLint, unit tests and production build;
- the standalone Model Passport page is still a controlled frontend shell;
  Product API v1.1 already supplies `GET /api/v1/models/active`, so the
  remaining work is browser integration rather than a missing backend contract;
- the owner-approved near-term scope is a research pilot with allocation-only
  decisions; hosted VM/reverse-proxy deployment is not implemented yet;
- company queue, PostgreSQL/object-storage adapters, corporate authentication,
  and company-contour deployment remain future work.

The former `pkg_5795ed2581eaa9af_9aacd3beb350725b` claim is historical and must not be presented as the current preprod package.

## Existing Calculation Boundary To Reuse

- `02_Code/01_PyMC/mmm_core/campaign_plan.py`: input normalization, daily flighting, budget reconciliation, and model capability validation.
- `02_Code/01_PyMC/mmm_core/model_package_reader.py`: immutable package metadata and serving policy.
- `02_Code/01_PyMC/mmm_core/forecast_engine.py`: posterior scoring and support checks.
- `02_Code/03_AC_forecast/ac_forecast.py`: verified forecast workflow and artifact generation.
- `02_Code/02_Budget_optimizer/budget_optimizer.py`: benchmark Scenarios 1-5 and constrained Scenario 6.
- `02_Code/02_Budget_optimizer/marketer_report.py`: stakeholder report generation from completed artifacts.
- `02_Code/01_PyMC/03_model_registry.py` and `02_Code/01_PyMC/mmm_core/model_registry.py`: registry resolution, activation, and rollback behavior.

The web layer must call this existing boundary. It must not copy adstock, saturation, scaling, posterior scoring, support gates, or optimizer mathematics.

## Frozen Architecture Boundary

Items 1-3 below are the target for a later company/multi-node deployment.
ADR 0014 accepts file-backed state and artifacts for one research-pilot server;
that adapter must preserve the same resource IDs, hashes and contracts.

1. The application records uploads, validation records, jobs, events, model references, result metadata, and audit history in PostgreSQL.
2. PostgreSQL is the source of truth for application state, not for large calculation artifacts.
3. Original uploads, normalized plans, JSON/CSV outputs, run cards, and Excel reports are stored outside PostgreSQL in approved artifact storage.
4. A background worker receives an immutable `job_id`, resolves the stored job inputs and verified model package, and invokes the existing tested calculation boundary in an isolated process.
5. The API request must not run long forecast, optimization, report, notebook, or PyMC work.
6. The web layer reads completed artifacts and maps them into a versioned DecisionResult; it does not recalculate model values.
7. Local and preprod application development can proceed independently of production model activation. Production remains fail-closed until its gates pass.
8. Product API discovery must preserve the exact `segment x channel x target`
   policy and must not collapse diagnostic side metrics into another target's
   reliability status.

See `04_Web_app/docs/adr/0001-source-of-truth-and-boundaries.md`.

## Canonical Lifecycle V1

Upload, validation, and calculation job are different resources. They must never share one mixed enum or infer one another's state from display text.

### Upload

`received -> parsed | rejected`

- `received`: the immutable source file and its hash were accepted for parsing.
- `parsed`: parsing produced a canonical candidate payload; this is not validation success.
- `rejected`: the file could not be accepted or parsed. Rejection reasons are separate machine-readable codes.

### Validation

`running -> valid | invalid`

- `running`: canonical validation is in progress.
- `valid`: no blocking validation errors remain; warnings may still exist.
- `invalid`: at least one blocking validation error prevents job creation.

### Job

`queued -> running -> cancel_requested -> succeeded | failed | cancelled | timed_out`

- `queued`: the immutable job definition exists and awaits execution.
- `running`: a worker owns the execution attempt.
- `cancel_requested`: cancellation was requested but has not yet been confirmed by the worker.
- `succeeded`, `failed`, `cancelled`, and `timed_out` are terminal states.

`cancel_requested` is entered only when cancellation is requested. A job with no cancellation request can move from `running` to its terminal outcome. A cancellation request is not itself proof that calculation stopped, and a completed result must not be overwritten by a retry.

Progress is not lifecycle state. Progress events use stages such as `prepare`, `forecast`, `benchmarks`, `scenario6`, `final_scoring`, and `report`, with timestamps, messages, and optional counters.

## Five Decision-Status Domains V1

Lifecycle states above describe resources. The five domains below describe the calculation and decision outcome. They answer different questions and must remain separate:

1. `calculation_status`: was the campaign calculated and with what coverage?
2. `campaign_scale_status`: how does total campaign scale compare with reviewed historical campaign episodes?
3. `cell_support_status`: where does the evaluated plan sit relative to cell-level support bounds?
4. `optimizer_status`: did Scenario 6 produce a safe automatic allocation outcome?
5. `business_decision_status`: is a business launch decision available under an approved commercial policy?

Every domain is represented as a status object:

```json
{
  "code": "calculated",
  "display_text": "Рассчитано"
}
```

Only `code` is a stable API enum. `display_text` is localized presentation text, can change without a contract version, and must never drive branching, persistence keys, or tests.

### `calculation_status`

| Machine code | Meaning | Example display text |
|---|---|---|
| `calculated` | All model-input budget intended for calculation was calculated. | Рассчитано |
| `partially_calculated` | A visible part of the uploaded budget or plan is outside model coverage or remains unallocated. | Рассчитано частично |
| `not_calculated` | No result was calculated for this campaign. A separate reason code is required. | Расчет не выполнен |

### `campaign_scale_status`

| Machine code | Meaning | Example display text |
|---|---|---|
| `within_historical_p95` | Budget and daily intensity are within reviewed historical p95. | Сопоставимо с историческими кампаниями |
| `between_historical_p95_p99` | Above historical p95 and within historical p99. | Крупная, но похожие кампании встречались |
| `between_historical_p99_and_robust_upper` | Above p99 and within robust observed upper. | Очень крупная, нужна повышенная осторожность |
| `above_historical_robust_upper` | Budget or daily intensity exceeds robust observed campaign support. | Выше надежной наблюдаемой зоны |
| `benchmark_unavailable` | Reviewed campaign-level support bounds are unavailable. | Исторический benchmark недоступен |

### `cell_support_status`

| Machine code | Meaning | Example display text |
|---|---|---|
| `within_p95` | Evaluated cells are inside p95 support. | Внутри p95 support-zone |
| `between_p95_p99` | At least one cell is above p95 and no cell is above p99. | Между p95 и p99 |
| `above_p99_within_robust_upper` | At least one cell is above p99 but no cell exceeds robust observed upper. | Выше p99, требуется ручная проверка |
| `above_robust_upper` | At least one cell exceeds robust observed upper. | Вне надежной наблюдаемой зоны |
| `not_evaluated` | Cell-level support was not evaluated for this result object. | Не оценено |

### `optimizer_status`

| Machine code | Meaning | Example display text |
|---|---|---|
| `best_safe_available` | A complete `best_safe` candidate exists under the frozen model and support gates. | Лучший безопасный план рассчитан |
| `partial_safe_available` | A safe calculable subset exists; the remainder requires manual allocation. | Частичный безопасный план |
| `no_safe_candidate` | Scenario 6 ran but produced no candidate eligible for automatic recommendation. | Безопасный автоматический план не найден |
| `gate_policy_blocked` | Scenario 6 could not form a legal donor/receiver search under gate policy. | Перераспределение недоступно по gate policy |
| `not_run` | Optimization was not run because an upstream condition blocked it or the approved job did not request it. | Оптимизация не запускалась |

`best_raw`, `best_safe`, and `no_safe_candidate` must remain explicit and distinct. `best_raw` may be present when no safe candidate exists, but it must never be auto-recommended. `no_safe_candidate` is an outcome, not permission to fall back to the unsafe raw candidate.

### `business_decision_status`

| Machine code | Meaning | Example display text |
|---|---|---|
| `allocation_only` | No approved commercial hurdle exists; the result can support allocation but not launch/cancel. | Бизнес-порог не настроен |
| `manual_review_required` | A hurdle exists but coverage, support, or other approved guardrails require a human decision. | Требуется ручное бизнес-решение |
| `meets_business_hurdle` | The evaluated result meets an approved and versioned business hurdle. | Выше бизнес-порога |
| `below_business_hurdle` | The evaluated result is below an approved and versioned business hurdle. | Ниже бизнес-порога |
| `not_evaluated` | Business evaluation was not performed. | Бизнес-решение не оценено |

The current policy maps to `allocation_only`. This is not a launch recommendation and does not approve a future hurdle.

Current `marketer_report_recommendations.csv` contains all five named columns, while scenario-level files contain the applicable subset. Their source values remain display strings. `04_Web_app/adapters/optimizer_result_adapter.py` now converts them through an explicit fail-closed mapping; string matching in the frontend remains prohibited.

## Contract Boundary V1

DecisionResult and application lifecycle are implemented v1 contracts. They
freeze the boundary that the future worker, API, persistence layer, and
frontend must use.

### Campaign Upload

Required business data:

- `campaign_name`;
- `segment`;
- `start_date` and `end_date`, or daily `date`;
- `geo`;
- `channel`;
- `budget_rub` or `spend_rub`;
- optional creative, flight, and comment fields.

Stored system metadata includes upload ID, original filename, SHA-256, actor ID, timestamp, parser version, and schema version. The original file remains immutable.

### Validation Result

Validation returns:

- normalized campaign summary and total budget;
- normalized daily-plan artifact reference;
- `blocking_errors[]` for malformed or unsupported inputs;
- `warnings[]` for support, model reliability, and business caveats;
- affected `segment x channel x geo` cells;
- reconciliation totals between source, normalized, and daily plans.

Blocking errors prevent job creation. Warnings remain visible and can still allow forecast execution.

### Decision Job

One immutable job describes the complete `forecast + optimizer + report` calculation and includes:

- job ID and idempotency key;
- normalized-plan artifact ID and SHA-256;
- job type and contract version;
- registry channel provenance or explicit-package mode, with resolved immutable
  package ID and expected fingerprint pinned in either case;
- scenario, optimizer, gate, and business-policy versions;
- posterior sample counts and deterministic seeds.

The API creates application state only. The worker performs calculation outside the request.

### Implemented Application Lifecycle V1

The lifecycle implementation is intentionally dependency-light and contains no
MMM calculations:

- `04_Web_app/contracts/application_lifecycle_v1.py`: immutable typed records,
  legal state combinations and transitions, timestamp/order checks, safe
  artifact references, JSON-to-domain parsing, and semantic validation;
- `04_Web_app/contracts/application_lifecycle_v1.schema.json`: Draft 2020-12
  wire schema for `campaign_upload_v1`, `validation_result_v1`,
  `decision_job_v1`, `job_event_v1`, `progress_event_v1`, and
  `application_error_v1`, all at version `1.0.0`;
- `04_Web_app/tests/fixtures/application_lifecycle_v1_happy_path_synthetic.json`:
  explicitly synthetic parsed-upload, valid-validation, successful-job path;
- `04_Web_app/tests/fixtures/application_lifecycle_v1_failure_path_synthetic.json`:
  explicitly synthetic rejected-upload, invalid-validation, and failed-job path;
- `04_Web_app/tests/test_application_lifecycle_v1.py`: schema, semantic,
  round-trip, path-safety, transition, cancellation, progress, selector, and
  terminal-outcome tests;
- `04_Web_app/docs/adr/0002-application-lifecycle-contract-v1.md`: rationale,
  ownership boundaries, and rules future layers must preserve.

JSON Schema validates the wire shape. Python entry points must additionally
call `parse_lifecycle_contract()` or `validate_lifecycle_payload()` because
timestamp ordering, budget reconciliation, state combinations, transition
legality, and relative counter bounds are semantic checks.

Lifecycle fixtures are application-contract examples only. They are not real
campaigns, model packages, calculation outputs, or evidence of model quality.

### DecisionResult

DecisionResult is job-level and supports one or more campaigns:

```text
DecisionResult
  job lineage
  model and policy lineage
  campaign_results[]
  artifacts[]
```

Each `campaign_results[]` item contains:

- source and normalized campaign passport;
- uploaded, model-input, calculated, and uncovered budget reconciliation;
- Scenarios 1-5 with p10/p50/p90 and applicable ROAS metrics;
- Scenario 6 attempts and audit summary;
- distinct `best_raw`, `best_safe`, and `no_safe_candidate` representation;
- selected allocation or an explicit reason no safe automatic plan exists;
- recommended `geo x channel` plan when available;
- the five status objects with stable code and separate display text;
- support/model warnings and affected cells;
- package ID, package fingerprint, registry event, policy versions, seeds, and hashes.

Artifact references contain an opaque artifact ID, kind, SHA-256, and an approved relative storage key or download capability. They must never expose a local absolute path. Existing local artifacts are evidence inputs; their workstation paths are not copied into the future contract.

### Implemented DecisionResult V1

The current implementation is intentionally dependency-light and does not duplicate MMM mathematics:

- `04_Web_app/contracts/decision_result_v1.py`: standard-library immutable domain models and semantic validation;
- `04_Web_app/contracts/decision_result_v1.schema.json`: Draft 2020-12 wire schema, contract name `decision_result_v1`, version `1.0.0`;
- `04_Web_app/adapters/optimizer_result_adapter.py`: reads completed optimizer/report artifacts, verifies declared hashes, records adapter version/hash, maps source display statuses to stable codes, and emits JSON-native DecisionResult;
- `04_Web_app/tests/fixtures/decision_result_v1_real_sanitized.json`: real-derived safe-S6 fixture for frontend and API tests;
- `04_Web_app/tests/fixtures/decision_result_v1_gate_blocked_sanitized.json`: real-derived gate-blocked fixture;
- `04_Web_app/tests/test_decision_result_v1.py`: schema, semantics, multi-campaign, path-safety, tamper, and fallback-policy tests.

The adapter command is:

```bash
python -B 04_Web_app/adapters/optimizer_result_adapter.py \
  --optimizer-output-dir <completed-optimizer-output-dir> \
  --output <completed-optimizer-output-dir>/decision_result_manifest_v1.json
```

The adapter is not the future execution worker. It starts only after optimizer and marketer artifacts have completed. It does not parse an upload, create a job, run forecast, search candidates, or persist application lifecycle state.

Scenario 6 is read from the marketer decision pool and enriched from finalist totals. Therefore a safe S6 remains visible with p10/p50/p90, ROAS, orders, basket bridge, best-safe ID and search audit even when materiality policy recommends S01. Gate-blocked S6 is represented as unavailable with no invented metrics. Search audit distinguishes configured attempt budget, attempts actually evaluated, kernel evaluations, unique allocations, scored/rejected candidates, convergence and budget-exhaustion state.

Adapter `1.0.1` fixes a verified legacy-unit defect: marketer-report
`orders_*_mln` columns contain raw order counts and must not be multiplied by
one million. The basket metric now carries the explicit unit
`turnover_bridge_from_avg_basket_rub`; it is an aggregate turnover bridge, not
an average-basket delta. See ADR 0004.

Adapter `1.0.2` maps the report generator's best-rank quality label
`Сопоставимо с историей` to stable code `reliable` and its blocked label
`Расчет невозможен` to `not_calculated`. Unknown display text remains
fail-closed. See ADR 0009.

`ResultOverview v1` is now the browser-facing projection over DecisionResult.
It adds ROAS p10/p50/p90, uploaded-versus-recommended allocation deltas,
UI-safe `best_raw`/`best_safe` summaries, canonical artifact download paths,
and an explicit diagnostic-only label for orders. It contains no model math
and never exposes raw candidate names or workstation paths. See ADR 0005.

## Implemented Local Execution Worker V1

The local worker uses the tested composite optimizer CLI as its process
boundary:

1. Accept and semantically validate one queued immutable `DecisionJobV1`.
2. Resolve and SHA-256-check normalized-plan, daily-flighting, and source-config
   artifacts through an artifact-store port.
3. Load the package pinned by the job through the existing registry and verify
   package ID, fingerprint, registration, inventory, and serving permission;
   never replace it silently with a newer channel pointer.
4. Verify gate, optimizer, business-policy, draws, seeds, and code pins.
5. Materialize an attempt-local execution config without changing the source
   job/config, then launch `budget_optimizer.py` in a separate process group.
6. Translate real JSON stdout into lifecycle progress; keep raw logs protected.
7. Handle cancellation, timeout, non-zero exit, and unexpected failures with
   distinct lifecycle outcomes.
8. Verify completed run lineage and call the existing result adapter with the
   original job ID and source-config SHA-256.
9. Persist local development events, errors, state, result, and worker run card
   through `LocalWorkerJournal`.

`budget_optimizer.py` already performs campaign preparation, Scenarios 1-5,
Scenario 6, posterior finalist scoring, and marketer report generation. The
worker therefore does not launch a second standalone forecast process for the
same job. No notebooks run and no calculation function is copied into the web
layer.

`LocalArtifactStore` and `LocalWorkerJournal` are development adapters. Future
queue, PostgreSQL, and object-storage adapters must preserve their frozen
contract behavior. See `04_Web_app/docs/adr/0003-local-execution-worker-v1.md`.

## Next Milestones

Each item is a separate reviewable milestone:

1. Completed: define DecisionResult v1, emit real manifests, verify source/output hashes, and add safe-S6 plus gate-blocked real-derived fixtures.
2. Completed: define versioned CampaignUpload, ValidationResult, DecisionJob,
   JobEvent, progress, and error contracts with happy/failure fixtures and
   semantic validation.
3. Completed: implement local Execution Worker v1 around the existing composite
   optimizer/report boundary, including immutable preflight, progress,
   cancellation, timeout, lineage verification, and DecisionResult composition.
4. Completed: add a localhost-only HTTP smoke path with file-backed state,
   bounded background execution, idempotency, progress polling,
   ResultOverview delivery and hash-checked artifact downloads.
5. Completed: implement canonical marketer upload, background campaign parsing
   and model-aware validation, isolated flighting artifacts and immutable
   DecisionJob creation over the same lifecycle contracts.
6. Completed: the versioned local runtime launcher, registry preflight,
   single-process lock and restart/recovery guardrails are implemented. Real
   localhost job `job_85c4b1ac16afa1a5e165` completed against pinned preprod
   package `pkg_807d3ddbae57a52a_9aacd3beb350725b`; DecisionResult,
   ResultOverview and the hash-checked marketer Excel were accepted. See ADR
   0010. Smoke sampling proves application integration only, not business
   effectiveness or production model readiness.
7. Completed for localhost: preserve the merged Phase 1 presentation and add
   the core marketer workflow over the stable API. Standard-profile job
   `job_66ae8290e5d41b825808` passed validation review, browser job creation,
   progress, result redirect, server-backed history, reopen, and hash-checked
   Excel download. See ADR 0013.
8. Completed and merged in PR #6: Product API v1.1, verified ModelPassport,
   readiness, error catalog, OpenAPI/schema discovery, paginated history,
   research-pilot configuration boundary and safe local retention. See ADR
   0014.
9. Completed in PR #7 for result pages: integrate the Phase 2 frontend against
    ResultOverview without copying status, metric or model-policy logic. The
    Model Passport shell still needs a typed client for the already implemented
    Product API v1.1 endpoint.
10. Completed on PR #9: require clean Python and frontend integration checks
    before merge, including generated-contract drift detection and production
    frontend build.
11. Package and accept one research-pilot server deployment: reverse proxy,
    HTTPS, simple access control, service supervision, disk monitoring, backup,
    scheduled retention and live browser acceptance.
12. When company-contour or multi-node scale is approved, replace file-backed
    state/artifacts with PostgreSQL, durable queue and object storage while
    preserving the frozen contracts.

Do not start a later milestone while an earlier contract or evidence gate is unresolved. Decisions requiring owner approval are listed only in `04_Web_app/OPEN_DECISIONS.md`.
