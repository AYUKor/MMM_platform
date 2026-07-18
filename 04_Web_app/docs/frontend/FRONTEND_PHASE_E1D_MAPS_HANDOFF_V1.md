# Frontend Phase E.1D Handoff: Maps

## Backend readiness

Backend Phase E.1C publishes a complete static point catalog and server-side
budget aggregates. Frontend Phase E.1D may render maps without implementing
geocoding or summing campaign/job rows.

The current catalog version is `geo_catalog_v1_2026_07_18`; all 220 active
turnover-serving geographies have reviewed WGS84 coordinates.

## Source contracts

| Screen | Endpoint | Contract |
|---|---|---|
| Map reference data | `GET /api/v1/meta/geo-catalog` | `geo_catalog_v1` |
| New-calculation validation | `GET /api/v1/validations/{validation_id}/view-v2` | `validation_result_v2` |
| Home workspace budget | `GET /api/v1/workspace/geo-budget` | `workspace_geo_budget_v1` |

Use generated TypeScript types and the existing fail-closed contract client.
Do not read CSV files from the browser.

## New-calculation map

Render `geo_points[]` from the validation response. The backend already gives:

- canonical `geo_id` and display name;
- latitude/longitude and `coordinates_status`;
- requested-budget money and share;
- approved channel IDs/display names;
- model-limitation boolean/count;
- region metadata;
- normalization status for explicit unknown handling.

Use `map_coverage` for the screen-level state. For `partial`, render all located
markers and a separate list/message for every unlocated identity and its total
budget. Never omit that budget from totals.

Map coverage is independent from model eligibility. An unknown coordinate does
not itself change file validity, but `job_creation_allowed` can still be false
when the active model has no permitted estimate for that geography. Do not
interpret `partial` as permission to bypass model limitations.

## Home map

Render `rows[]` from workspace geo budget. `total_budget_rub`, `campaigns_n` and
`budget_share` are authoritative server aggregates. Do not recompute them from
history or validation responses. Alias spellings are already merged by
canonical `geo_id`.

The workspace endpoint includes only validations referenced by saved jobs and
deduplicates repeated references by `validation_id`. Two independently uploaded
campaigns with the same display name remain two workspace campaigns.

An empty workspace is `unavailable` with zero rows and zero money; this is a
valid empty state, not a transport error.

## State behavior

- `available`: render all markers;
- `partial`: render located markers and prominently disclose unlocated names,
  budget and share;
- `unavailable`: do not fabricate markers; render the controlled empty state;
- unsupported contract: fail closed through the typed client;
- HTTP error: use the existing retry/error treatment.

Only `coordinates_status=canonical` is renderable. There is no approximate or
guessed status.

## Attribution and map base

Point coordinates contain geographical data from GeoNames, licensed under CC
BY 4.0. The frontend must retain visible attribution appropriate to the chosen
map composition.

This phase does not approve a tile provider, runtime map API, regional polygon
asset or its license. Prefer a reviewed bundled static geometry for the pilot.
Do not add Google/Yandex/OSM geocoding or external tile/network calls without a
separate approved architecture and data-governance decision.

## Prohibited frontend behavior

- no fuzzy alias matching;
- no guessed coordinates;
- no dropping unknown rows or budget;
- no parsing `... ещё N` strings;
- no frontend budget aggregation;
- no hardcoded duplicate geo catalog;
- no local file paths;
- no changes to MMM, forecast, optimizer or recommendation semantics.
