# ADR 0007: Local Marketer Application Flow

- Status: Accepted
- Date: 2026-07-15
- Scope: campaign upload, parsing, model-aware validation and job creation

## Context

HTTP Smoke v1 accepted a prebuilt immutable `DecisionJob`. That proved the
browser-to-worker boundary but still required a developer to assemble JSON.
The marketer journey needs to start from a campaign file and must surface
input/model problems before posterior calculation starts.

The existing `mmm_core.campaign_plan` is already the canonical parser,
normalizer, daily-flighting builder and model-capability validator. The web
application must orchestrate it rather than duplicate its logic.

## Decision

`04_Web_app/services/local_campaign_service.py` implements the local
application flow:

1. `POST /api/v1/uploads` stores one bounded CSV/XLSX file under a
   server-generated storage key, records SHA-256 and returns `202`.
2. Parsing runs in the background through the canonical campaign-plan parser.
   A parsed canonical CSV becomes an immutable `campaign_upload_parsed`
   artifact. Schema/row failures produce a rejected upload.
3. `POST /api/v1/uploads/{upload_id}/validations` starts background
   model-aware validation against one pinned registry channel and package ID.
4. The service calls `prepare_campaign_from_config`; it does not copy campaign
   normalization, flighting or capability logic.
5. A valid result contains campaign previews, budget reconciliation, model and
   policy lineage, warnings, normalized plan, daily flighting and validation
   artifact identities. Unsupported model cells fail closed and are returned
   as affected `campaign x geo x channel x target` cells when evidence exists.
6. `POST /api/v1/validations/{validation_id}/jobs` creates an immutable queued
   `DecisionJob v1`. Sampling overrides are bounded, package/policies are
   pinned, and tracked source changes must be committed before a real job can
   be created.
7. The existing HTTP dispatcher and Execution Worker own all later forecast,
   optimizer and report work.

Local application records and files use separate idempotency ledgers. Repeated
requests with the same key and content return the same resource; a reused key
with different content returns `409`.

## Isolated Campaign Preparation

`mmm_core.campaign_plan.prepare_campaign_from_config` now accepts optional
`paths.validated_output_dir` and `paths.flighting_output_dir`. Existing configs
without these fields retain the established typed project folders.

The local validation service and Execution Worker set these paths to
validation- or attempt-specific folders. This removes server-job collisions
without changing parser, flighting, forecast or optimizer mathematics.

## Input Scope V1

The first marketer path supports the canonical campaign brief accepted by
`read_campaign_brief` in CSV, TSV, XLSX or XLS form. The specialized
`x5_agency_kpi_v1` workbook adapter is not guessed from a filename and is not
enabled through this route yet. It requires a separate explicit input profile
and contract because it contains source-specific mapping and coverage rules.

## Limitations

- Upload parsing and validation use the local process executor, not a durable
  distributed queue.
- XLS files still depend on the locally available spreadsheet engine.
- Local size limits do not replace malware scanning, DLP or archive-bomb
  protection required in the company contour.
- User identity is a local development actor until SSO/RBAC is approved.
- Real calculation remains preprod-only while OOT evidence is unavailable.

## Validation

Tests cover canonical background parsing, upload idempotency, filename path
rejection, stdlib multipart parsing, HTTP fail-closed validation, real preprod
registry/package validation, campaign preview and artifact hashes, and
immutable job construction. The full core contract suite verifies that output
path isolation did not alter MMM, forecast or optimizer behavior.

