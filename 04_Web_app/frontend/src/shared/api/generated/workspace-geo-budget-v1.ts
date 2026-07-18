/* Generated from ../../contracts/workspace_geo_budget_v1.schema.json. Do not edit manually. */

export type Row = CanonicalRow | UnavailableRow;

export interface WorkspaceGeoBudgetV1 {
  contract_name: "workspace_geo_budget_v1";
  schema_version: "1.0.0";
  catalog_version: string;
  status: "available" | "partial" | "unavailable";
  display_text: string;
  total_budget_rub: number;
  campaigns_n: number;
  geographies_n: number;
  coverage: BudgetCoverage;
  rows: Row[];
}
export interface BudgetCoverage {
  status: "available" | "partial" | "unavailable";
  located_geographies_n: number;
  unlocated_geographies_n: number;
  unlocated_geographies: GeoIdentity[];
  located_budget_rub: number;
  unlocated_budget_rub: number;
  unlocated_budget_share: number | null;
}
export interface GeoIdentity {
  geo_id: string;
  geo_display_name: string;
}
export interface CanonicalRow {
  geo_id: string;
  geo_display_name: string;
  latitude: number;
  longitude: number;
  coordinates_status: "canonical";
  region_id: string;
  region_display_name: string;
  total_budget_rub: number;
  campaigns_n: number;
  budget_share: number | null;
}
export interface UnavailableRow {
  geo_id: string;
  geo_display_name: string;
  latitude: null;
  longitude: null;
  coordinates_status: "unavailable";
  region_id: null;
  region_display_name: null;
  total_budget_rub: number;
  campaigns_n: number;
  budget_share: number | null;
}
