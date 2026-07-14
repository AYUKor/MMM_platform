# ADR 0003: Local Execution Worker V1

- Status: Accepted
- Date: 2026-07-15
- Scope: immutable job execution, subprocess isolation, progress, cancellation,
  timeout, completed-result composition, and local audit evidence

## Context

DecisionResult v1 defines the completed business response. Application
lifecycle v1 defines uploads, validation, immutable jobs, legal state
transitions, progress, and safe errors. A missing boundary remained between a
queued `DecisionJobV1` and the existing calculation workflows.

The worker must not create a second forecast or optimizer implementation. The
existing `budget_optimizer.py` CLI already performs the complete application
job: campaign preparation, benchmark Scenarios 1-5, adaptive Scenario 6,
posterior finalist scoring, and marketer-report generation. Launching a
separate forecast CLI for the same job would duplicate calculation work and
create two competing result lineages.

Company queue, PostgreSQL, object storage, authentication, deployment runtime,
and production timeout policy are not approved yet. The first worker therefore
needs a dependency-light local implementation whose ports can later be backed
by approved infrastructure.

## Decision

### 1. One composite calculation process

`04_Web_app/worker/execution_worker.py` launches the existing
`02_Code/02_Budget_optimizer/budget_optimizer.py` CLI with `subprocess.Popen`.
The process runs outside an HTTP request and owns the complete
`forecast + scenarios + optimizer + report` calculation. The worker never
imports or copies adstock, saturation, posterior, support, gate, or search
mathematics.

### 2. Immutable inputs are verified before execution

The worker accepts only a semantically valid queued `DecisionJobV1`. Before
starting calculation it verifies:

- normalized-plan, daily-flighting, and source-workflow-config sizes and
  SHA-256 values through an artifact resolver;
- pinned registry channel, package ID, package fingerprint, registered
  inventory, and model-package validity;
- gate-policy version from the verified package manifest;
- optimizer and business-policy files by both policy ID and SHA-256;
- business decision mode;
- Scenario 6 attempt budget, posterior draws, and deterministic seeds;
- the pinned Git code reference in the local v1 runtime.

Any mismatch fails closed before the optimizer can publish a result. The
worker never replaces a package pin with a newer channel package.

### 3. Source config and execution config are different artifacts

The job pins an immutable logical workflow-config artifact. Runtime-local paths
do not exist until the worker resolves stored artifacts. The worker therefore
copies the verified normalized plan and pinned daily flighting into a new
attempt directory and materializes a protected execution config.

Only environment routing is injected: attempt-specific run ID, local input and
output paths, registry root, exact policy paths, package pin, draws, and seeds.
The source config remains unchanged. The worker run card records both the
source config SHA-256 and materialized execution-config SHA-256.

The materialized config may contain server-local absolute paths because the
existing CLI requires filesystem paths. It is a protected worker artifact and
must never be returned by the API or browser.

### 4. Every attempt has isolated audit output

Local v1 writes one attempt under:

```text
<runtime-root>/<job-id>/attempt_<number>/
```

The worker refuses to overwrite an existing attempt directory. It records:

- current `DecisionJobV1` state;
- append-only job events;
- append-only progress events;
- browser-safe application errors;
- protected combined subprocess log;
- materialized execution config;
- optimizer output directory;
- DecisionResult v1 on success;
- local worker run card.

`LocalWorkerJournal` is a development persistence adapter, not a claim of
PostgreSQL durability. `LocalArtifactStore` is a development storage adapter,
not approved enterprise object storage.

### 5. Progress comes from real calculation events

The worker reads line-delimited JSON already emitted by the calculation core.
It maps `forecast_progress` and `optimizer_progress` into canonical
`ProgressEventV1` stages. Non-JSON stdout and raw exception details remain only
in the protected log.

For multi-campaign jobs, the worker caches the campaign position announced by
`candidate_generation`, because later optimizer phases contain the campaign
name but not its index. Percent complete is monotonic across campaign phases;
it is presentation progress and never changes job lifecycle state.

### 6. Cancellation and timeout are explicit terminal semantics

The worker starts a separate process group. A cancellation probe emits
`running -> cancel_requested`, terminates the process group, and confirms
`cancel_requested -> cancelled`. Cancellation creates no `ApplicationError`.

A configured timeout terminates the process and produces `timed_out` plus a
retryable browser-safe error. Non-zero optimizer exit produces `failed` and a
safe error; detailed stdout, traceback, and local paths remain protected.

No production SLA is implied. The local CLI requires an explicit timeout while
`OD-004` remains open.

### 7. Completed artifacts must still match the job

Exit code zero is not success by itself. The worker verifies the optimizer run
card and model-resolution artifact against the job's flighting hash, package
identity, policy hashes, search budget, draws, and seeds. It then calls the
existing completed-result adapter.

The adapter now accepts optional worker-provided `job_id` and source workflow
config SHA-256. Manual adapter use remains backward compatible. This preserves
one identity from queued job through completed DecisionResult and prevents a
second derived job ID from appearing at the end of the workflow.

### 8. Worker v1 supports registry-channel jobs only

Application lifecycle v1 can represent an explicit package selector, but the
existing completed-result artifacts require registry package identity and
event provenance. Worker v1 therefore executes only a pinned
`registry_channel` selector and rejects `explicit_package` fail-closed. Support
for explicit package execution requires a separate reviewed adapter, not an
implicit fallback.

## Known Limitations

- No HTTP API, queue consumer, PostgreSQL adapter, object-storage adapter,
  authentication, authorization, container, or deployment configuration is
  implemented.
- Local file polling is the only cancellation adapter.
- Retry claiming and distributed idempotency remain future persistence work.
- The existing campaign-preparation module still writes normalized and daily
  intermediate files into the project's established typed data folders. Unique
  worker run IDs avoid filename collisions in local v1, but preparation output
  destinations must become configurable before concurrent production workers.
- The marketer report is generated inside the composite optimizer process. The
  worker can report result validation after process exit but does not infer a
  report-start event from human-readable CLI text.
- Production timeout/search profiles remain approval-gated under `OD-004`.

## Validation

Worker tests cover:

- successful isolated subprocess execution and one `job_id` through result;
- real JSON progress translation for a two-campaign synthetic process;
- SHA-256 tampering before process start;
- non-zero process failure without path leakage;
- timeout and process termination;
- cancellation without error misclassification;
- completed adapter override of job identity and source config lineage.

The synthetic subprocess and result object are explicitly test-only and are not
model-quality evidence. Existing real optimizer runs continue to validate the
completed-result adapter separately.

## Consequences

- The next local milestone can put a thin HTTP boundary around a tested worker
  port instead of invoking calculation code inside a request.
- Future PostgreSQL, queue, and object-storage implementations must implement
  the existing lifecycle, journal, artifact-resolver, and cancellation
  semantics rather than inventing a second vocabulary.
- No model refit, forecast recomputation, optimizer-policy change, or model
  activation occurred in this milestone.

## Related Documents

- `04_Web_app/docs/adr/0001-source-of-truth-and-boundaries.md`
- `04_Web_app/docs/adr/0002-application-lifecycle-contract-v1.md`
- `04_Web_app/contracts/application_lifecycle_v1.py`
- `04_Web_app/contracts/decision_result_v1.py`
- `04_Web_app/worker/execution_worker.py`
- `04_Web_app/tests/test_execution_worker_v1.py`
- `04_Web_app/OPEN_DECISIONS.md`
