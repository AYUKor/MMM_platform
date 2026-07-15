# ADR 0015: Research Pilot Deployment v1

- Status: Accepted
- Date: 2026-07-15
- Scope: one-server packaging, model transfer, service supervision, HTTPS boundary, health, retention and backup

## Context

Product API v1.1 and the marketer workflow are implemented, but a browser on
another machine cannot use a backend that runs only on the model owner's
MacBook. The accepted next stage is a controlled research pilot on one
external Linux server. It does not need the later company-contour database,
distributed queue or SSO topology.

The existing registry check was designed for the model-development machine
and required the original training panel on every resolution. Forecast serving
uses exported design metadata, support bounds, denominators, warm-start state
and posterior NetCDF files; it does not read that panel. Transferring the panel
to an external pilot would increase data exposure without changing the result.

## Decision

### Deployment Topology

The pilot uses one Ubuntu VM, one stdlib Python Product API process, one worker
and file-backed state. The Python process binds only to `127.0.0.1`. Nginx
terminates HTTPS, enforces basic authentication, serves the React `dist`,
applies upload limits and proxies API routes. Frontend and API use one origin.

Systemd supervises the backend and schedules health, terminal-resource
retention and backup. The deployment renderer emits configuration but never
credentials or TLS private keys.

### Two Registry Verification Modes

`full_lineage` remains the default for model registration, research and refit.
It verifies the serving inventory, source panel and full package lineage.

`serving_bundle` is explicit and fail-closed. It verifies:

- registration metadata content hash;
- pinned channel and package ID;
- byte-for-byte equality of the complete registered serving inventory;
- `posterior_ready` package invariants;
- equality of package and registration fingerprints.

It retains the registered source-panel SHA-256 as provenance but does not
require or copy the source panel. Unknown modes fail. The mode is passed through
backend preflight, campaign validation, immutable worker preparation and the
optimizer execution config. MMM response mathematics is unchanged.

### Model Bundle

The model is not committed to Git. A versioned archive transfers exactly the
registered inventory plus one registration, activation event and channel
pointer. Every file has SHA-256 and size in an internal manifest. Archive
verification rejects path traversal, symlinks, duplicates, unexpected members
and tampering. Installation never overwrites a different file and publishes
the channel pointer last.

The training panel, raw datasets, prior campaign inputs, generated optimizer
outputs and secrets are excluded.

### Runtime State And Recovery

Application state, runtime attempts and artifacts live under one dedicated
data root. Backup is allowed only when all uploads, validations and jobs are
terminal. The scheduled operation stops the backend, rechecks idle state,
archives the three runtime roots with hashes and starts the backend in a
`finally` path. Restore accepts an empty target only and verifies all restored
files. Source is restored from Git; the model is restored from its independent
bundle.

Retention uses the same quiesced rule because the backend owns the state lock
while running. Health requires both `/health` and `/ready` plus a minimum-free-
disk threshold.

## Consequences

The product can be tested by remote marketers without connecting to the
owner's laptop. The serving server receives only the model artifacts required
for calculation, while model-data lineage remains recorded. Deployment and
rollback become reproducible and tied to a Git commit, package ID and config.

The pilot remains single-node. Maintenance causes a short scheduled outage and
is refused while work is active. PostgreSQL, a durable distributed queue,
object storage, SSO/RBAC, multi-node failover and company security controls
remain later adapters. `preprod_restricted`, missing sealed OOT and
`allocation_only` semantics remain visible and unchanged.

## Validation

- MMM core: 78 tests passed, 2 fixture-dependent tests skipped.
- Web backend: 66 tests passed, 10 source-artifact-dependent tests skipped.
- Deployment tests cover panel exclusion, bundle tamper detection, idempotent
  install, render guards, active-job backup refusal, restore and health/disk.
- The real preprod package produced a verified 58-file, 450,344,722-byte
  payload with no source panel.
- A clean temporary installation passed backend `--check-only`, built a valid
  Model Passport, served live health/readiness routes, ran a real posterior
  forecast with support `within_support`, and completed a smoke optimizer run
  through marketer Excel generation without the training panel.
