# ADR 0013: Real core marketer flow acceptance

Status: accepted for local pre-production testing on 2026-07-15.

## Context

The earlier localhost acceptance proved that the HTTP API, worker, optimizer,
DecisionResult, ResultOverview, and Excel download could complete one smoke
job. It did not prove that the merged Phase 1 frontend could drive the full
marketer workflow or that the standard server sampling profile completed from
the browser-facing lifecycle.

## Acceptance path

One canonical four-row CSV campaign was processed through the real local
application boundary:

1. `POST /api/v1/uploads` stored and parsed the immutable source.
2. Model-aware validation produced
   `validation_42334052aafec5b5b299` with status `valid`.
3. The validation review was opened at
   `/calculations/new?validationId=validation_42334052aafec5b5b299`.
4. The browser created immutable job `job_66ae8290e5d41b825808`.
5. The progress page polled lifecycle and progress records until success.
6. The browser redirected to the completed DecisionResult page.
7. The completed job appeared in server-backed calculation history and could
   be reopened from that history.
8. The marketer workbook was downloaded by opaque artifact ID and its
   SHA-256 was verified.

## Evidence

- campaign: `Local E2E acceptance`;
- period: 2026-08-01 through 2026-08-14;
- uploaded and model-input budget: RUB 1,900,000;
- model coverage: 100 percent;
- channels: 2; geographies: 2;
- package: `pkg_807d3ddbae57a52a_9aacd3beb350725b`;
- package status: `preprod_restricted`;
- Scenario 6 attempt budget: 2,048;
- search draws: 128; finalist draws: 600;
- evaluated attempts: 366; kernel evaluations: 666;
- unique allocations: 39; finalists: 5;
- Scenario 6 converged and did not exhaust the search budget;
- selected recommendation: S01, because the higher S6 allocation did not pass
  the materiality gate;
- result: `result_8ec732b9beedf3a47685`;
- Excel artifact: `artifact_8680fdb78deeb02354a7`;
- Excel size: 13,555 bytes;
- Excel SHA-256:
  `8dd3d76ed5cd3b49d94f96c6921d1887672d9dded338dc5c791f564c261ad21a`;
- observed end-to-end duration: about 42 seconds.

## Decision

The current localhost implementation is accepted as a complete local core
marketer workflow for continued product and frontend testing. The browser is
allowed to orchestrate lifecycle operations and present contract data, but it
must not calculate MMM effects, optimizer decisions, or quality statuses.

The browser file-picker could not be confirmed through the automated macOS
dialog because the automation surface left the native `Open` action disabled.
The same file was uploaded through the same HTTP endpoint, then the validation,
job creation, progress, redirect, history, result, and download steps were
verified in the live browser. This is recorded as a tooling limitation, not as
evidence that the file input is broken.

## Boundaries

This acceptance proves local application integration. It does not:

- activate the model in production;
- provide sealed OOT evidence;
- approve a ROAS or contribution-margin launch/cancel threshold;
- replace PostgreSQL, durable queueing, approved object storage, SSO/RBAC,
  monitoring, backup, or company deployment controls;
- prove that the selected media allocation is causally optimal.

