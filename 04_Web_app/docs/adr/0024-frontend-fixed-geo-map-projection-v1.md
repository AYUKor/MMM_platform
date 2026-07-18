# ADR 0024: frontend fixed geo-map projection v1

## Status

Accepted for Frontend Phase E.1D on 2026-07-18.

This ADR selects the browser renderer and local outline left open by ADR 0023.
It does not change the canonical geo catalog, backend aggregation or model
coverage policy.

## Context

The Home and campaign-validation screens need one stable visual coordinate
system for canonical WGS84 city points. The map must not resize itself around a
particular campaign, because identical cities would otherwise move between
screens and a sparse campaign would misleadingly fill the whole canvas. Runtime
tiles, browser geocoding and a heavy GIS dependency are outside the product and
security boundary.

Russia spans a wide longitude range and crosses the antimeridian. The chosen
projection therefore needs an explicit central meridian and longitude wrapping,
while remaining small enough to implement and test locally.

## Decision

### Projection

Both `workspace` and `campaign` modes use one spherical Albers Equal Area
projection with fixed parameters:

- first standard parallel: `45° N`;
- second standard parallel: `70° N`;
- central meridian: `100° E`;
- latitude of origin: `55° N`;
- SVG view box: `0 0 1200 680`.

Longitude difference from the central meridian is wrapped into `[-π, π)` before
projection. Latitude and longitude inputs remain canonical WGS84 degrees from
the backend; the browser does not geocode or correct them.

For radians `phi`, wrapped `deltaLambda` and the fixed parameter values:

```text
n = (sin(phi1) + sin(phi2)) / 2
C = cos(phi1)^2 + 2 * n * sin(phi1)
rho0 = sqrt(C - 2 * n * sin(phi0)) / n
rho = sqrt(C - 2 * n * sin(phi)) / n
theta = n * deltaLambda

projectedX = rho * sin(theta)
projectedY = rho0 - rho * cos(theta)
```

The current fixed numerical terms are:

```text
n = 0.823399700986228
C = 1.6644630243886747
rho0 = 0.6821469074832438
```

Projected coordinates are transformed into the shared view box using these
constants:

```text
SCALE = 880.2744673041848
OFFSET_X = 659.5017197759643
OFFSET_Y = 522.4001925283919

screenX = OFFSET_X + SCALE * projectedX
screenY = OFFSET_Y - SCALE * projectedY
```

These values are based on the pinned outline asset and fixed 36-pixel horizontal
fit margin. They are product constants, not bounds recalculated from the points
returned for a workspace or campaign. Responsive layout scales the complete SVG
through `preserveAspectRatio="xMidYMid meet"`; it does not alter projected marker
coordinates.

### Outline and runtime boundary

The local `04_Web_app/frontend/src/assets/maps/russia-outline-v1.svg` asset uses
the same projection and view box. It is generated offline from Natural Earth
Admin 0 – Countries 1:50m v5.1.1, feature `ADM0_A3=RUS`, then simplified by
0.5 view-box pixels. Its source archive and output hashes are recorded in
`04_Web_app/frontend/src/assets/maps/RUSSIA_OUTLINE_SOURCE.md`.

The frontend imports the SVG with Vite `?raw`, so geometry is part of the build
output and does not trigger a runtime map-asset fetch. Marker projection uses a
small local helper. No map SDK, `d3-geo`, tile source, runtime GeoJSON parser,
Google, Yandex or OpenStreetMap request is introduced.

The visible attribution is exactly:

> Координаты городов: GeoNames, CC BY 4.0.
>
> Контур карты: Natural Earth, public domain.

### Geometry boundary

The Natural Earth polygon is a schematic, de facto visual context at 1:50m. It
contains no product labels or claim lines and must not be interpreted as an
authoritative legal border or a statement about disputed territory. City marker
identity, budget and coverage remain backend-contract facts; the outline does
not establish model support.

## Rejected alternatives

- Per-response min/max fitting: moves identical cities and exaggerates sparse
  campaigns.
- Runtime tiles or geocoding: adds an external data and network boundary and can
  make placement irreproducible.
- Web Mercator with an arbitrary crop: is less suitable for the wide northern
  extent and still requires a fixed antimeridian policy.
- A GIS rendering dependency: is unnecessary for one reviewed outline and a
  bounded point layer, while increasing bundle and maintenance cost.

## Consequences

- A canonical coordinate pair always projects to the same SVG coordinate in
  Home and campaign validation.
- Resize, theme and response contents cannot change marker placement.
- The static 43,339-byte outline is available offline and adds no map-runtime
  dependency.
- The equal-area property and Russia-centred parameters provide a stable
  country-wide overview, but the result is not intended for distance, route,
  cadastral or legal-boundary analysis.
- Changing projection parameters, affine constants or source geometry requires
  a new versioned asset, updated hashes and projection regression tests.
