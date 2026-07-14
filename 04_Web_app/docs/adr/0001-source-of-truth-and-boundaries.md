# ADR 0001: Source Of Truth And Application Boundaries

- Status: Accepted
- Date: 2026-07-14
- Scope: enterprise web application integration boundary

## Context

The existing X5 MMM calculation system already performs campaign normalization, posterior forecast, benchmark scenarios, support-aware Scenario 6 optimization, registry resolution, run-card generation, and marketer reporting. Its tested behavior lives under `02_Code/`, and immutable packages and result evidence live under `03_Outputs/`.

A removed web prototype duplicated calculation logic and returned synthetic results. Repeating that pattern would create two mathematical implementations, break package lineage, and allow browser-facing behavior to diverge from the verified calculation core.

The future application also needs durable asynchronous state and artifact delivery. Large uploads, posterior outputs, CSVs, run cards, and Excel workbooks are not relational application-state records and should not be stored as PostgreSQL blobs.

Finally, the current package is restricted to preprod because sealed OOT evidence is unavailable. That model-governance gate must not be confused with the engineering ability to build and test a local/preprod application against verified artifacts.

## Decision

### 1. The web layer does not duplicate MMM mathematics

The API, persistence layer, worker adapter, and frontend contain no copied implementation of adstock, saturation, scaling, posterior scoring, support gates, forecast, or optimizer logic. Calculation behavior remains owned by:

- `02_Code/01_PyMC/mmm_core`;
- `02_Code/03_AC_forecast`;
- `02_Code/02_Budget_optimizer`.

Synthetic fixtures may test presentation behavior only when explicitly labeled. They are never production evidence and never substitute for a real verified DecisionResult fixture.

### 2. The worker invokes the existing tested calculation boundary

Long-running work is executed by a background worker in an isolated process. The worker resolves an immutable `job_id`, verifies the registry package and fingerprint, builds a versioned configuration, and invokes the existing tested workflow boundary. It does not run notebooks and does not reimplement calculations.

The HTTP request creates or reads application state; it does not perform forecast, optimization, report generation, or PyMC training.

### 3. DecisionResult is job-level and supports multiple campaigns

One completed job produces one versioned DecisionResult. The root contains job/model/policy lineage and `campaign_results[]`, allowing a single uploaded workbook or job to contain one or more campaigns without changing the top-level contract.

Each campaign result keeps calculation, campaign scale, cell support, optimizer, and business decision statuses separate. Scenario 6 preserves `best_raw`, `best_safe`, and `no_safe_candidate` as distinct outcomes.

### 4. Artifacts are stored outside PostgreSQL

Original uploads, normalized plans, JSON/CSV outputs, run cards, model-derived technical artifacts, and Excel reports are stored in approved external artifact storage. PostgreSQL stores their opaque IDs, kinds, hashes, approved relative storage keys, ownership, timestamps, and lifecycle metadata.

Future API contracts and database records do not expose workstation absolute paths.

### 5. PostgreSQL is the source of truth for application state

PostgreSQL owns uploads, validation records, jobs, execution attempts, lifecycle states, progress events, model references, result metadata, artifact metadata, actor/audit records, and idempotency records. Calculation files do not replace this application-state ledger.

The model registry remains the source of truth for package channel resolution and immutable package identity. PostgreSQL does not override registry activation.

### 6. Production activation is separate from local/preprod development

Local and preprod application work may use the verified preprod package and real derived fixtures while displaying its restrictions. Production package promotion remains fail-closed and requires its own model-governance evidence, including valid sealed OOT.

No application feature may relabel a `preprod_restricted` package as production-ready.

## Consequences

- Frontend and API development must wait for versioned contracts and one real verified DecisionResult fixture, but not for production model activation.
- A worker adapter and artifact mapper are required between application state and the existing CLI workflows.
- The adapter must verify package, policy, input, and artifact hashes and must translate local artifact paths into opaque references.
- PostgreSQL backup does not by itself back up calculation artifacts; external artifact storage needs its own retention and disaster-recovery controls.
- Multi-campaign jobs are supported without creating one result contract per workbook shape.
- Changes to MMM mathematics remain in the existing calculation repository boundary and require their own model validation, package revision, replay, and registry process.

## Non-Goals

This ADR does not select a queue, object-storage product, deployment platform, identity provider, retention period, business hurdle, OOT window, or model-approval role. Those approval-gated items are recorded in `04_Web_app/OPEN_DECISIONS.md`.

This ADR creates no frontend, backend, API, database, worker, queue, authentication, Docker, or model code.

## Related Documents

- `AGENTS.md`
- `04_Web_app/PROJECT_BRIEF.md`
- `04_Web_app/CURRENT_TRUTH.md`
- `04_Web_app/PROJECT_HANDOFF.md`
- `04_Web_app/OPEN_DECISIONS.md`
