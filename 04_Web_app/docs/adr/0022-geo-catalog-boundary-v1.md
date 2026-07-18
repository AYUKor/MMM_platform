# ADR 0022: geo catalog boundary v1

## Status

Accepted as the backend prerequisite for future maps.

Implemented by ADR 0023 and catalog `geo_catalog_v1_2026_07_18`; the original
null-coordinate interim state is historical.

## Context

The application needs stable geography identities for validation, result and
workspace views. Existing presentation strings could shorten long lists, and
the project has no reviewed coordinate catalog. Guessing coordinates or using
request-time external geocoding would make map output irreproducible and could
place a campaign budget in the wrong location.

## Decision

1. Machine-readable geography arrays come from normalized campaign rows and
   scenario allocations, never from shortened presentation text.
2. A value containing `... еще N` is invalid machine data and fails closed.
3. `geo_catalog_v1` provides stable deterministic `geo_id` values and separate
   display names.
4. Latitude/longitude can be populated only from a reviewed canonical catalog.
5. Missing coordinates are represented as null with status `unavailable`.
6. Request-time external geocoding, city-name guessing and synthetic map points
   are prohibited.
7. Validation and workspace geo-budget projections reconcile money by the same
   geo identities used by result contracts.
8. `scenario_media_plan_v2` publishes those same identities and approved
   channel display names for every paginated allocation row and aggregate.

## Consequences

- all 15 geographies in the acceptance campaign survive validation, result and
  media-plan projection;
- frontend can build list/table views immediately and a map only after a
  canonical coordinate dataset is approved;
- no location is visually fabricated;
- deterministic IDs are identity keys, not claims that two naming aliases are
  the same place; alias governance remains a data-quality responsibility.
