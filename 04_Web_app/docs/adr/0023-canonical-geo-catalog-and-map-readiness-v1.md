# ADR 0023: canonical geo catalog and map readiness v1

## Status

Accepted for backend Phase E.1C on 2026-07-18. This implements the coordinate
catalog boundary introduced by ADR 0022; it does not select a frontend map
renderer, polygon asset or tile provider.

## Context

The Home and campaign-validation screens need geography markers and budget
aggregates. Stable geo IDs already existed, but coordinates were deliberately
null because no reviewed source or alias policy had been approved. Browser-side
geocoding, fuzzy matching or dropping unknown rows would make campaign money
irreproducible and could silently place it in the wrong geography.

The active turnover package exposes 220 serving geographies. The control
campaign contains 45 rows, 15 geographies, three channels and 267,818,706 RUB.
The implementation must cover the full serving set, not only those 15 names.

## Decision

1. Version `geo_catalog_v1_2026_07_18` is repository data under
   `04_Web_app/data/geo_catalog/`.
2. The 220 static WGS84 point coordinates come from the GeoNames Russia dump
   dated 2026-07-18, archive SHA-256
   `e900a407f811b53a1bf51612fe6f1a809af275e43a02b85f63c7bfddd75e4035`,
   licensed under CC BY 4.0.
3. Existing E.1A `geo_id` values remain unchanged. The canonical catalog maps
   those IDs to display labels, coordinates, region metadata and source record
   IDs.
4. Aliases are versioned explicit data. Deterministic lexical normalization is
   allowed; fuzzy, nearest-name and nearest-coordinate matching are prohibited.
5. Unknown and ambiguous geographies receive stable input-derived IDs, null
   coordinates and explicit normalization evidence. Their rows and budget stay
   in validation/workspace responses.
6. `available`, `partial` and `unavailable` are computed from returned rows.
   Partial responses publish unlocated identities, budget and budget share.
7. Workspace budget and campaign counts are aggregated on the server by
   canonical `geo_id` from job-backed validations; aliases merge, repeated
   validation references are ignored and one campaign counts once per geo.
8. Backend preflight fails closed unless every active turnover-serving geo has
   one canonical coordinate pair.
9. `GET /api/v1/meta/geo-catalog`, validation `view-v2` and workspace
   `geo-budget` are the only browser sources for this map data. Frontend does
   not join history rows or calculate budget aggregates.
10. Runtime geocoding and external map API calls remain prohibited.

## Consequences

- the full static catalog is `available` at 220/220;
- the control campaign is `available` at 15/15, with exact budget and no
  shortened machine strings;
- a campaign containing one known and one unknown geo returns `partial`,
  including the unknown money; map coverage itself does not block calculation,
  while independent model-support policy may still block an unsupported geo;
- changing the active serving inventory without updating the catalog makes
  backend preflight fail;
- point markers are ready for Phase E.1D, but a reviewed map base/polygon
  source, attribution placement and frontend rendering remain separate work.
