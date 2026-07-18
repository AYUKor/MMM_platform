/* Generated from ../../contracts/historical_model_geo_budget_v1.schema.json. Do not edit manually. */

export type HistoricalModelGeoBudgetV1 = {
  [k: string]: unknown;
} & {
  contract_name: "historical_model_geo_budget_v1";
  schema_version: "1.0.0";
  record_origin: "verified_model_package_artifact" | "model_package_artifact_unavailable";
  status: "available" | "partial" | "unavailable";
  title: "Исторический рекламный бюджет в данных модели";
  display_text: string;
  period_display_text: string;
  package_id: string;
  model_version: string | null;
  artifact_id: string | null;
  artifact_version: string | null;
  catalog_version: string;
  period_start: string | null;
  period_end: string | null;
  spend_columns_version: string | null;
  total_budget_rub: number | null;
  geographies_n: number;
  coverage: Coverage;
  rows: Row[];
  limitations: Limitation[];
  updated_at_utc: string | null;
};
export type Row = CanonicalRow | UnavailableRow;

export interface Coverage {
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
  historical_total_budget_rub: number;
  budget_share: number;
  active_days_n: number;
  active_rows_n: number;
}
export interface UnavailableRow {
  geo_id: string;
  geo_display_name: string;
  latitude: null;
  longitude: null;
  coordinates_status: "unavailable";
  historical_total_budget_rub: number;
  budget_share: number;
  active_days_n: number;
  active_rows_n: number;
}
export interface Limitation {
  code: string;
  display_text: string;
}
