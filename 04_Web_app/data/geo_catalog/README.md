# Canonical Geo Catalog V1

This directory contains the reviewed static geography identity and coordinate
data used by browser-safe map contracts. Runtime code reads these files only;
it does not call a geocoder or an external map service.

## Versioned files

- `geo_catalog_v1.csv`: 281 canonical geographies in active turnover serving;
- `geo_aliases_v1.csv`: 466 explicit deterministic aliases for those identities.

Catalog version: `geo_catalog_v1_2026_11_05`. The earlier revisions
`geo_catalog_v1_2026_07_18` (220 geographies) and `geo_catalog_v1_2026_10_27`
(223 geographies) are described in "Revision history".

Changing an identity, coordinate, alias or source snapshot requires a new
reviewed catalog version and regression against the active serving inventory.
Existing `geo_id` values are the E.1A SHA-256 identities of normalized model
labels and must not be reassigned.

## Coordinate source and license

Coordinates come from the static GeoNames Russia dump `RU.zip`, snapshot dated
2026-10-27 (server `Last-Modified` 2026-10-27 02:49:02 GMT, 15,263,830 bytes,
413,135 records). The downloaded archive SHA-256 is:

`07b78bbd84a1906cdf5be77f50451011e896c6c653dd9e37aedf916823c48b2e`

The first revision (2026-07-18) used a snapshot with SHA-256
`e900a407f811b53a1bf51612fe6f1a809af275e43a02b85f63c7bfddd75e4035`. That archive
was not available when the second revision was prepared, so every one of its 220
records was re-checked against the new snapshot by GeoNames record ID. All 220
records exist in the new snapshot with identical latitude and longitude text, which
is why the whole catalog carries the new snapshot metadata and no coordinate of an
existing geography changed.

GeoNames publishes latitude/longitude in WGS84 and distributes its geographical
database under the Creative Commons Attribution 4.0 License. Attribution:

> Contains geographical data from GeoNames (https://www.geonames.org/),
> licensed under CC BY 4.0.

Primary source pages:

- https://download.geonames.org/export/dump/
- https://download.geonames.org/export/dump/readme.txt
- https://www.geonames.org/export/
- https://creativecommons.org/licenses/by/4.0/

The GeoNames record ID is retained in
`coordinates_source_record_id`; the source date, archive hash and review status
are retained per row. Region and federal-district fields are static catalog
metadata for grouping; they are not generated in a browser request.

## Selection and review policy

1. Active labels were taken from `historical_support_bounds.csv` of the serving
   model package at `scope=geo` and `target=turnover_per_user`.
2. Candidate records were matched by normalized exact name and expected
   feature type: populated place, first-level administrative unit or district.
3. Ambiguous names were resolved only with existing panel/reference evidence;
   fuzzy or nearest-coordinate guessing was not used.
4. Four explicit source-record decisions are retained by record ID:
   `КАБАРДИНО-БАЛКАРСКАЯ РЕСПУБЛИКА` -> `554667`,
   `КАРАЧАЕВО-ЧЕРКЕССКАЯ РЕСПУБЛИКА` -> `552927`,
   `КИРОВСК` -> `548392` (Leningrad region), and
   `СТАВРОПОЛЬ` -> `487846`.
5. The resulting guard is exact: every active turnover-serving geography of the
   serving package (223 for the daily Q2 package, 217 for the weekly package)
   must resolve to one canonical catalog entry with a complete coordinate pair.

The point coordinate is suitable for locating a label/marker. It is not a
municipal or regional polygon and must not be presented as a precise campaign
boundary.

## Alias policy

Normalization is limited to case, surrounding/repeated whitespace, `Ё` -> `Е`
and Unicode-hyphen normalization. A non-canonical business spelling resolves
only when it is explicitly present in `geo_aliases_v1.csv`.

- one alias -> one canonical `geo_id`;
- unknown -> explicit `unknown`, null coordinates, budget retained;
- ambiguous -> explicit `ambiguous`, null coordinates, budget retained;
- production catalog load fails if one registered alias points to more than one
  canonical identity.

Examples such as `Санкт-Петербург`, `Санкт Петербург`, `СПБ` and
`г. Санкт-Петербург` resolve to the same existing `geo_id`.

## Revision history

| Version | Geographies | Aliases | Snapshot | Change |
|---|---|---|---|---|
| `geo_catalog_v1_2026_07_18` | 220 | 402 | 2026-07-18, `e900a407…` | First reviewed catalog, equal to the active turnover serving geographies of the first production model package. |
| `geo_catalog_v1_2026_10_27` | 223 | 408 | 2026-10-27, `07b78bbd…` | Adds the three geographies that entered the model roster with the Q2 refresh; all earlier records are unchanged and re-verified against the new snapshot. |
| `geo_catalog_v1_2026_11_05` | 281 | 466 | 2026-10-27, `07b78bbd…` | Adds the 58 rest-of-oblast units of the weekly joint panel (57 model units and Республика Бурятия (кроме городов)); all earlier records are unchanged apart from the version column. |

Geographies added on 2026-10-27, all matched by normalized exact name and expected
feature type, with the GeoNames record ID kept per row:

- `БАБУШКИН`: record `2027276` (populated place, Республика Бурятия). Seven records
  in the snapshot carry this name; the others are a district of Moscow, a place in
  Novosibirsk oblast and four streams. The Buryatian town was selected by existing
  reference evidence, not by guessing: the Rosstat municipal entry `г Бабушкин`
  (code `816241030011000`, population 4,209), the Q2 geo reference coordinates (about
  0.45 km from the GeoNames point) and the weather station assigned to the geography
  (Novoselenginsk, Buryatia).
- `ГЕЛЕНДЖИК`: record `561667` (second-level administrative centre, Краснодарский
  край), the only record with this name.
- `ЯМАЛО-НЕНЕЦКИЙ АВТОНОМНЫЙ ОКРУГ`: record `1486462` (first-level administrative
  unit), the only record with this name. As for the other region geographies the
  point is the GeoNames centroid of the region, not a place of activity.

Each new geography has a canonical alias; cities also have the `г. <name>` alias and
the hyphenated label has its space variant, following the existing alias rules.

Geographies added on 2026-11-05: the 58 rest-of-oblast units of the weekly joint
model panel (fourth pass panel v3), labelled `<ОБЛАСТЬ> (КРОМЕ ГОРОДОВ)`. A unit is the
part of an oblast outside the model's own cities of that oblast (for example
`РОСТОВСКАЯ ОБЛАСТЬ (КРОМЕ ГОРОДОВ)`). It is not a GeoNames feature, so no new
coordinate was looked up: each unit carries the GeoNames record, coordinates, region
and federal district of its oblast entry already in the catalog (the region
centroid). On a map the unit and its oblast therefore share a marker; the point
locates the label, not the unit's territory. The display name is
`<oblast display name> (кроме городов)`. Each unit has its canonical alias only;
the label is generated by the package build and is not typed by planners, because
media plans name the oblast and the package routes oblast rows to its units.
57 of them are units of the model. `РЕСПУБЛИКА БУРЯТИЯ (КРОМЕ ГОРОДОВ)` has panel
spend (both ТС5 directions) but no usable target week, so the model has no unit
there; it is in the catalog so that the historical budget map locates all panel
money.

## Alias normalization in campaign preparation

Campaign preparation uses the catalog's normalized uppercase label as the
model-package lookup key and keeps `geo_display_name` for browser output. The
original spelling, canonical display label, normalization status and rule are
retained in the campaign preparation audit evidence.
