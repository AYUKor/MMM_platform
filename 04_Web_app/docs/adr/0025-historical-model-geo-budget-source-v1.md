# ADR 0025: historical model geo-budget source v1

## Status

Accepted for backend Phase E.1E on 2026-07-19. Frontend Phase E.1F is a
separate milestone.

## Context

The Home map currently reads `workspace_geo_budget_v1`, which summarizes
campaigns processed by the application. That is valid calculation-history
evidence, but it is not the historical advertising activity used to fit the
active model. Presenting it as historical model spend gives the map the wrong
business meaning.

The required source is the panel registered with the selected model package.
Reading that full Parquet file on every Home request would couple product
latency and deployment dependencies to a large training artifact. Mutating the
already registered model directory or its inventory would also invalidate its
immutable package identity.

## Decision

1. `historical_geo_budget_v1` is built offline from the panel identity stored
   in model-registry registration metadata. A workstation path is never part
   of the API contract.
2. The versioned spend policy contains exactly six non-overlapping model spend
   columns: Digital Performance, total OOH, Indoor, radio, national TV and
   regional TV. Raw OOH components cannot be selected together with total OOH.
3. The builder projects only date, model geography and those six spend
   columns. Null, infinite or negative spend fails closed; values are never
   clipped or silently imputed.
4. The deterministic Parquet is bound to package identity, source-panel hash,
   policy hash and output hash. A deterministic JSON metadata sidecar repeats
   the small aggregate rows for a Python runtime that does not ship a Parquet
   engine.
5. Because the registered model package is immutable, the derived artifact is
   stored in a package-bound registry extension:
   `package_artifacts/<package_id>/package_artifacts_manifest_v1.json`.
   The extension repeats the registration and panel identities and is verified
   before serving. The original registration, model manifest and inventory are
   not rewritten.
6. `GET /api/v1/model/historical-geo-budget` reads only that small hash-bound
   aggregate evidence and joins the canonical Phase E.1C geo catalog. It never
   opens the source panel.
7. Unknown geographies retain their rows and money with null coordinates and
   explicit `partial` or `unavailable` coverage. There is no fuzzy geocoding or
   silent dropping.
8. `GET /api/v1/workspace/geo-budget` remains unchanged as application-history
   evidence. Frontend Phase E.1F will switch only the Home map to the new
   endpoint; the campaign map keeps validation `view-v2`.
9. Campaign count is not calculated or published because the registered panel
   has no approved campaign identifier.
10. Old packages without the extension return a controlled `unavailable`
    payload. There is no fallback to workspace campaign history.

## Consequences

- Home can show the correct model-history meaning without scanning the full
  panel or adding PyArrow to the serving runtime;
- package immutability and registration hashes remain valid;
- the artifact must be built once for each package that should expose this
  view;
- research-pilot bundle packaging of package extensions remains a separate
  deployment task because Phase E.1E does not change deployment;
- exact real financial aggregates remain in ignored local package evidence and
  are not committed to the external source repository.
