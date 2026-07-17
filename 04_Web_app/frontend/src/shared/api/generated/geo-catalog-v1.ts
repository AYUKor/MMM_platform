/* Generated from ../../contracts/geo_catalog_v1.schema.json. Do not edit manually. */

export interface GeoCatalogV1 {
  contract_name: "geo_catalog_v1";
  schema_version: "1.0.0";
  catalog_version: string;
  status: "available" | "partial" | "unavailable";
  display_text: string;
  geographies_n: number;
  entries: Entry[];
}
export interface Entry {
  geo_id: string;
  geo_display_name: string;
  latitude: number | null;
  longitude: number | null;
  coordinates_status: "canonical" | "unavailable";
  region_id: string | null;
  region_display_name: string | null;
}
