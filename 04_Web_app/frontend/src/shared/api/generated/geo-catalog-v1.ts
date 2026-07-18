/* Generated from ../../contracts/geo_catalog_v1.schema.json. Do not edit manually. */

export type Entry = CanonicalEntry | UnavailableEntry;

export interface GeoCatalogV1 {
  contract_name: "geo_catalog_v1";
  schema_version: "1.0.0";
  catalog_version: string;
  coordinates_source: string;
  coordinates_source_version_or_date: string;
  coordinates_license: "CC BY 4.0";
  status: "available" | "partial" | "unavailable";
  display_text: string;
  geographies_n: number;
  coverage: Coverage;
  entries: Entry[];
}
export interface Coverage {
  status: "available" | "partial" | "unavailable";
  located_geographies_n: number;
  unlocated_geographies_n: number;
  unlocated_geographies: GeoIdentity[];
}
export interface GeoIdentity {
  geo_id: string;
  geo_display_name: string;
}
export interface CanonicalEntry {
  geo_id: string;
  geo_display_name: string;
  latitude: number;
  longitude: number;
  coordinates_status: "canonical";
  region_id: string;
  region_display_name: string;
}
export interface UnavailableEntry {
  geo_id: string;
  geo_display_name: string;
  latitude: null;
  longitude: null;
  coordinates_status: "unavailable";
  region_id: null;
  region_display_name: null;
}
