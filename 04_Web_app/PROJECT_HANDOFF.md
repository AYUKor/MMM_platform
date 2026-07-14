# X5 MMM Web Application Handoff

## Purpose

This handoff defines the frozen integration boundary for the future enterprise application. Current package, run, QA, and blocker facts live only in `04_Web_app/CURRENT_TRUTH.md` and must be verified from its cited evidence before implementation.

As of 2026-07-14:

- the verified serving channel is `preprod`;
- that pointer resolves to `pkg_807d3ddbae57a52a_9aacd3beb350725b` with fingerprint `807d3ddbae57a52ad184f94cd5442cdefd97764fe3903e5b250b5d04cd26c62c`;
- the package is `preprod_restricted`, not production-active;
- the latest verified optimizer run is `optimizer_agency_may_tsx_surgical_s6_v3_14072026`;
- the current business mode is `allocation_only`;
- there is no web application code under `04_Web_app`.

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

1. The application records uploads, validation records, jobs, events, model references, result metadata, and audit history in PostgreSQL.
2. PostgreSQL is the source of truth for application state, not for large calculation artifacts.
3. Original uploads, normalized plans, JSON/CSV outputs, run cards, and Excel reports are stored outside PostgreSQL in approved artifact storage.
4. A background worker receives an immutable `job_id`, resolves the stored job inputs and verified model package, and invokes the existing tested calculation boundary in an isolated process.
5. The API request must not run long forecast, optimization, report, notebook, or PyMC work.
6. The web layer reads completed artifacts and maps them into a versioned DecisionResult; it does not recalculate model values.
7. Local and preprod application development can proceed independently of production model activation. Production remains fail-closed until its gates pass.

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

Current `marketer_report_recommendations.csv` already contains all five named columns, while scenario-level files contain the applicable subset. Their values are display strings, so they do not yet implement this machine-code contract. A future adapter must use an explicit, versioned, tested mapping; string matching in the frontend is prohibited.

## Contract Boundary V1

The following is a frozen design boundary, not an implemented schema.

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
- registry channel or explicit immutable package ID;
- scenario, optimizer, gate, and business-policy versions;
- posterior sample counts and deterministic seeds.

The API creates application state only. The worker performs calculation outside the request.

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

## Worker Integration Rule

The first worker adapter must use the tested CLI workflows as process boundaries:

1. Load the immutable job by `job_id` from PostgreSQL.
2. Resolve upload, normalized-plan, configuration, and artifact references.
3. Resolve the package through the existing registry and verify package ID, fingerprint, registration, and inventory.
4. Create an immutable run configuration with versions and seeds.
5. Launch the existing forecast, optimizer, and marketer-report workflows in a separate process.
6. Read their run cards and artifacts, verify hashes, and map completed values into DecisionResult.
7. Persist application state and artifact metadata; keep large artifacts outside PostgreSQL.

No notebooks run in this flow. No existing calculation function is copied into the application.

## Next Milestones

Each item is a separate reviewable milestone:

1. Define versioned CampaignUpload, ValidationResult, DecisionJob, JobEvent, and DecisionResult schemas; create one DecisionResult fixture from verified real run artifacts.
2. Emit or assemble one canonical `decision_result_manifest_v1.json` and verify every source/output hash.
3. Implement the worker adapter around the existing calculation boundary with a local HTTP smoke path.
4. Add PostgreSQL application-state persistence and approved external artifact storage.
5. Implement API endpoints and asynchronous event delivery against the frozen contracts.
6. Build the marketer workflow on the real fixture and stable API.
7. Add approved SSO/RBAC, security controls, observability, backup/restore, and company deployment configuration.

Do not start a later milestone while an earlier contract or evidence gate is unresolved. Decisions requiring owner approval are listed only in `04_Web_app/OPEN_DECISIONS.md`.
