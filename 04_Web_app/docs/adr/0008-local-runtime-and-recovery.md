# ADR 0008: Local Runtime And Recovery

- Status: Accepted
- Date: 2026-07-15
- Scope: one-command local launch, preflight, process lock and restart recovery

## Context

The local HTTP application can accept campaign files, validate them and run
the real worker, but its raw CLI requires many paths and does not define what
happens to process-local work after a restart. A stale `running` status is
misleading, while blindly resuming an interrupted optimizer attempt can run
the same budget search twice.

## Decision

`04_Web_app/backend_runtime.py` reads one versioned JSON config, verifies the
pinned registry channel/package and package inventory, records a protected
runtime card, acquires a single-instance file lock and starts the localhost
server. The tracked config contains no workstation path or secret.

Restart recovery is fail-closed:

- queued jobs are dispatched again because no attempt has started;
- deterministic upload parsing and model validation are resubmitted;
- running or cancel-requested jobs become retryable failures with code
  `LOCAL_BACKEND_RESTARTED` and an auditable lifecycle event;
- an interrupted attempt is never represented as still running and is never
  silently resumed;
- an unexpected background exception writes a protected traceback and moves
  the browser-safe job to a retryable terminal failure instead of leaving a
  stale queued/running status;
- a second process cannot own the same local state directory.

Git cleanliness for new real jobs is scoped to calculation/backend source.
Uncommitted frontend-only files do not block MMM execution, while changes in
`mmm_core`, forecast, optimizer, contracts, adapters, API, services or worker
must be committed so the job can pin a truthful code reference.

## Consequences

The frontend team has one stable localhost address and one reproducible start
command. Recovery is intentionally conservative and may require a user retry
after a hard process stop. Company deployment still needs durable queue
claims/leases and transactional state; the local file lock is not a
distributed coordination mechanism.

## Validation

Tests cover config/package pinning, channel drift rejection, the
single-instance lock, queued-job recovery and fail-closed interrupted-job
recovery. HTTP health exposes recovery counts without local paths.
