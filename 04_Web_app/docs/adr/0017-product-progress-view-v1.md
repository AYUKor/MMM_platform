# ADR 0017: Product Progress View V1

Status: Accepted for backend Phase B review

Date: 2026-07-16

## Context

Application lifecycle v1 already exposed append-only technical progress events.
Those events are suitable for audit and worker recovery, but not as a stable
product API: they contain internal stage names, historical percentages and a
calculation order that the browser would otherwise have to reinterpret.

The Phase B progress page needs one reload-safe response with a campaign
summary, queue state, nine product stages, real Scenario 6 counters, report
publication and safe errors. It must not infer ETA, expose a temporary winner
or publish result metrics before terminal success.

## Decision

Add `job_progress_view_v1` as a read-only projection over persisted lifecycle
resources and expose it at:

```text
GET /api/v1/jobs/{job_id}/progress-view
```

Keep `ProgressEventV1` and `/progress` unchanged. Centralize internal-to-product
mapping in `services/job_progress_view.py`; do not duplicate it in the HTTP
handler or frontend.

The contract always contains P01-P09 in a fixed order. It excludes an overall
percent and ETA. Scenario 6 counters are included only when present in real
events or result artifacts; unavailable safe/blocked counts remain `null`.

Report status is a separate object. A succeeded job is rejected by the
projection unless both result and required marketer report have been
published. Current worker tests require report events to follow final scoring.

Add a separate static `mmm_fact_catalog_v1` endpoint with 20 reviewed facts.
Facts are not job state and never use live generation.

## Alternatives Considered

### Let the frontend map raw ProgressEventV1

Rejected because every browser client would reproduce worker knowledge,
internal terms and failure semantics. A worker refactor could then silently
break the page without changing a public contract.

### Replace ProgressEventV1

Rejected because existing jobs, tests and audit records depend on it. An
additive projection preserves backward compatibility.

### Publish a timer-based percent or ETA

Rejected because scenario runtime is not linear. Real stage and attempt
counters are more honest than a visually precise but unsupported number.

### Publish the current best Scenario 6 candidate

Rejected because an intermediate candidate may fail final posterior scoring or
support policy. Results and recommendations remain terminal resources.

## Consequences

- A frontend progress page can use one typed endpoint.
- Browser text is Russian and path-safe; raw phases/logs remain protected.
- Refresh and duplicate polling are deterministic and read-only.
- Old progress streams remain readable.
- The current package-scoring implementation exposes Scenario 6 attempts and
  finalists but not safe/blocked aggregates.
- Product stages P03-P05 are checkpoints over a batched scenario calculation,
  not claims that six independent subprocesses run sequentially.
- Frontend Phase B still requires a separate PR against this contract.

## Verification

Contract tests cover fixed stage order, queue/running/terminal states,
timestamps, path safety, counters, missing optional values, report behavior,
one-campaign enforcement, recovery across attempts and raw-contract
compatibility. Worker tests verify real event translation and report ordering.
HTTP tests cover 200, 404, 409, 503, schema publication and the facts endpoint.

No MMM, forecast, optimizer, Scenario 6 scoring or recommendation source is
changed by this decision.
