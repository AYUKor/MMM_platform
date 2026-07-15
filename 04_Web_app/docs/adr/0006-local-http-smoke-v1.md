# ADR 0006: Local HTTP Smoke V1

- Status: Accepted
- Date: 2026-07-15
- Scope: localhost job submission, background execution, polling and downloads

## Context

Lifecycle v1, Execution Worker v1, DecisionResult v1 and ResultOverview v1 are
implemented, but a browser cannot call Python classes directly. A first HTTP
boundary is needed before frontend integration. No web framework, production
database, durable queue, object storage, SSO or company deployment standard is
approved or installed in the source-only repository.

The HTTP milestone must prove the asynchronous boundary without creating a
second calculation engine or representing local file persistence as an
enterprise runtime.

## Decision

`04_Web_app/api/http_smoke.py` implements a localhost-only development server
with Python standard-library HTTP and a bounded `ThreadPoolExecutor`.

The first route set is intentionally job-first:

- `GET /health`;
- `POST /api/v1/jobs` with one queued `DecisionJob v1`;
- `GET /api/v1/jobs/{job_id}`;
- `GET /api/v1/jobs/{job_id}/progress`;
- `GET /api/v1/jobs/{job_id}/errors`;
- `GET /api/v1/jobs/{job_id}/result`;
- `GET /api/v1/jobs/{job_id}/overview`;
- `POST /api/v1/jobs/{job_id}/cancel`;
- `GET /api/v1/artifacts/{artifact_id}/download`.

HTTP request threads never run the optimizer. `POST /jobs` validates and
persists the immutable contract, enforces a local idempotency ledger, submits
one background task and returns `202`. A fresh `ExecutionWorker` is created for
every job because worker instances contain mutable per-attempt state.

`MirroredWorkerJournal` keeps the protected worker audit and simultaneously
updates browser-safe local state. Polling therefore sees real running status
and progress rather than only queued and terminal states.

Artifact download accepts only an opaque artifact ID. The server resolves the
path internally, enforces runtime-root containment and verifies size plus
SHA-256 immediately before sending bytes. Result JSON contains canonical
download paths and no workstation paths.

The server binds only to `127.0.0.1` or `localhost`. CORS is restricted to
configured localhost frontend origins. Responses use `nosniff` and `no-store`.

## Deliberate Limitations

- This milestone accepts an already valid immutable `DecisionJob`; marketer
  multipart upload and background campaign validation are the next application
  service milestone.
- Local JSON files are development state, not PostgreSQL.
- `ThreadPoolExecutor` is a process-local dispatcher, not a durable queue.
- A process restart does not reclaim unfinished jobs.
- The default concurrency is one because campaign preparation still writes
  some intermediates into shared typed project folders.
- There is no authentication, RBAC, TLS, malware scanning, retention policy,
  quota or approved external artifact storage.
- Model activation remains `preprod_restricted` and production OOT is still a
  separate model-governance blocker.

## Validation

HTTP tests cover fast asynchronous response, duplicate idempotent submission,
idempotency conflict, result readiness, ResultOverview delivery, hash-checked
download, tamper rejection, mirrored progress, response path safety and the
localhost bind guard. Existing lifecycle, worker and result tests remain
unchanged.

## Consequences

The frontend can now integrate against a real local HTTP lifecycle while the
next backend milestone creates uploads, validations and immutable jobs from a
marketer file. Production infrastructure can later replace local state,
dispatcher and artifact adapters without changing lifecycle/result contracts
or MMM mathematics.

