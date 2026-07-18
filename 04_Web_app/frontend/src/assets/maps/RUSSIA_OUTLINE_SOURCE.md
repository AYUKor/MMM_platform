# Russia outline v1: source and licence

## Artifact

- Browser asset: `russia-outline-v1.svg`.
- Generated: 2026-07-18, offline.
- Raw size: 43,339 bytes.
- SHA-256:
  `df5f1a3851bf4707301560ca2f7b6407add33d02de2a8f22a2ab20d211275d8d`.
- SVG coordinate space: fixed `viewBox="0 0 1200 680"`.

The asset is imported into the production bundle with the Vite `?raw` import.
It does not require a browser-time request to Natural Earth, a tile service or
another map provider.

## Source

The outline was derived from Natural Earth **Admin 0 – Countries**, 1:50m,
version 5.1.1:

- product page:
  <https://www.naturalearthdata.com/downloads/50m-cultural-vectors/50m-admin-0-countries-2/>;
- pinned source archive:
  <https://naturalearth.s3.amazonaws.com/5.1.1/50m_cultural/ne_50m_admin_0_countries.zip>;
- source archive SHA-256:
  `5fed433373581fa648920435f937d95f2d3c0200e067409c6478dcdf1b853139`.

The offline extraction selected the feature where `ADM0_A3=RUS`. It retained
the country multipolygon, projected it into the application view box, simplified
each projected ring with a tolerance of 0.5 view-box pixels and rounded output
coordinates to one decimal place. The output contains geometry only: no place
labels, political labels, borders of federal subjects or separate claim lines.

The same fixed spherical Albers Equal Area projection used by the frontend was
used to generate the SVG. Its parameters and exact affine transform are recorded
in `04_Web_app/docs/adr/0024-frontend-fixed-geo-map-projection-v1.md`.

## Licence

Natural Earth data is in the public domain. The relevant upstream terms are:

- Natural Earth terms of use:
  <https://www.naturalearthdata.com/about/terms-of-use/>;
- public-domain licence copy in the Natural Earth vector repository:
  <https://github.com/nvkelso/natural-earth-vector/blob/master/LICENSE.md>.

The visible product attribution is still retained for source transparency:

> Координаты городов: GeoNames, CC BY 4.0.
>
> Контур карты: Natural Earth, public domain.

## Product-use boundary

Natural Earth Admin 0 geometry is a small-scale, schematic, de facto map
dataset. This local outline is only a visual frame for canonical city budget
points. It is not an authoritative legal boundary, cadastral source or statement
about sovereignty, jurisdiction or disputed territory. The application must not
add political labels or infer model coverage from the polygon.
