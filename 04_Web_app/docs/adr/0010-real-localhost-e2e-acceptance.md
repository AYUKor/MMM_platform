# ADR 0010: Real Localhost E2E Acceptance

Date: `2026-07-15`

## Context

Unit and integration tests had verified the contracts, worker, upload flow and
local runtime separately. A product-ready local backend also needed evidence
that one real browser-style request could cross every implemented boundary
without bypassing package, policy, hash or artifact controls.

## Decision

Accept the local backend foundation after one complete job through:

1. canonical campaign upload and completed model-aware validation;
2. immutable `DecisionJob v1` creation;
3. registry resolution of preprod package
   `pkg_807d3ddbae57a52a_9aacd3beb350725b`;
4. existing optimizer/report CLI execution in the background worker;
5. `DecisionResult v1` adapter `1.0.2` and `ResultOverview v1` projection;
6. marketer Excel download through an opaque artifact ID with SHA-256 check;
7. workbook inspection and visual rendering of every sheet.

The accepted job is `job_85c4b1ac16afa1a5e165`, result
`result_4f866ba87bd7dd06f515`, code commit `f576210`, and Excel artifact
`artifact_28e7ba84da4fc45de755`. The downloaded workbook SHA-256 is
`65e2a26c45357e7ad862520a1204050dfc9b8ed15e7b3d8505413b47acc21c82`.

## Evidence And Scope

- package fingerprint and 55-file inventory passed runtime preflight;
- the job completed with deterministic smoke sampling: 64 Scenario 6 transfer
  checks, 16 search draws and 32 final draws;
- DecisionResult and ResultOverview contained no workstation paths;
- artifact download size and SHA-256 matched the contract;
- the three workbook sheets contained no formula errors or local paths;
- wrapped explanations were fully visible after report-layout correction;
- web/backend tests passed `51/51`; core backend tests passed `75/75` with two
  explicit fixture skips.

## Non-Claims

This acceptance does not prove that the smoke campaign is commercially
effective, that Scenario 6 found a global optimum, or that the model is ready
for production activation. The package remains `preprod_restricted` because
sealed OOT evidence is unavailable. Business mode remains `allocation_only`
because no ROAS or contribution-margin hurdle is approved.

## Consequences

Frontend development may integrate locally against the frozen lifecycle,
DecisionResult and ResultOverview contracts. Company deployment still requires
durable database/queue/storage adapters, SSO/RBAC, security controls,
observability and approved infrastructure without changing MMM mathematics.
