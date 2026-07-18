# Canonical Geo Catalog V1

This directory contains the reviewed static geography identity and coordinate
data used by browser-safe map contracts. Runtime code reads these files only;
it does not call a geocoder or an external map service.

## Versioned files

- `geo_catalog_v1.csv`: 220 canonical geographies in active turnover serving;
- `geo_aliases_v1.csv`: explicit deterministic aliases for those identities.

Catalog version: `geo_catalog_v1_2026_07_18`.

Changing an identity, coordinate, alias or source snapshot requires a new
reviewed catalog version and regression against the active serving inventory.
Existing `geo_id` values are the E.1A SHA-256 identities of normalized model
labels and must not be reassigned.

## Coordinate source and license

Coordinates come from the static GeoNames Russia dump `RU.zip`, snapshot dated
2026-07-18. The downloaded archive SHA-256 was:

`e900a407f811b53a1bf51612fe6f1a809af275e43a02b85f63c7bfddd75e4035`

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

1. Active labels were taken from `historical_support_bounds.csv` at
   `scope=geo` and `target=turnover_per_user`.
2. Candidate records were matched by normalized exact name and expected
   feature type: populated place, first-level administrative unit or district.
3. Ambiguous names were resolved only with existing panel/reference evidence;
   fuzzy or nearest-coordinate guessing was not used.
4. Four explicit source-record decisions are retained by record ID:
   `КАБАРДИНО-БАЛКАРСКАЯ РЕСПУБЛИКА` -> `554667`,
   `КАРАЧАЕВО-ЧЕРКЕССКАЯ РЕСПУБЛИКА` -> `552927`,
   `КИРОВСК` -> `548392` (Leningrad region), and
   `СТАВРОПОЛЬ` -> `487846`.
5. The resulting guard is exact: all 220 active turnover-serving geographies
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

Campaign preparation uses the catalog's normalized uppercase label as the
model-package lookup key and keeps `geo_display_name` for browser output. The
original spelling, canonical display label, normalization status and rule are
retained in the campaign preparation audit evidence.
