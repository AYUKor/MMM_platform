/* Generated from ../../contracts/scenario_media_plan_v1.schema.json. Do not edit manually. */

export type OpaqueId = string;
export type ScenarioId = "S01" | "S02" | "S03" | "S04" | "S05" | "S06";
export type NullablePositiveInteger = number | null;
export type QualityStatus = "safe" | "caution" | "blocked" | "unavailable";
export type NullableString = string | null;
export type NullableNumber = number | null;

export interface ScenarioMediaPlanV1 {
  contract_name: "scenario_media_plan_v1";
  schema_version: "1.0.0";
  record_origin: "application_runtime" | "sanitized_fixture";
  job_id: OpaqueId;
  result_id: OpaqueId;
  campaign_id: OpaqueId;
  scenario: Scenario;
  source_artifact: SourceArtifact;
  grain: "geo_channel_total";
  filters: Filters;
  pagination: Pagination;
  totals: Totals;
  filtered_totals: FilteredTotals;
  rows: MediaPlanRow[];
  aggregates: Aggregates;
  map: Map;
  working_media_plan: ArtifactAvailability;
  /**
   * @minItems 1
   */
  limitations: [Limitation, ...Limitation[]];
  updated_at_utc: string;
}
export interface Scenario {
  scenario_id: ScenarioId;
  title: string;
  status: "completed";
  is_selected: boolean;
  safe_rank: NullablePositiveInteger;
  raw_rank: NullablePositiveInteger;
  quality_status: QualityStatus;
  quality_display_text: string;
}
export interface SourceArtifact {
  artifact_id: OpaqueId;
  kind: "recommended_allocations_csv";
  sha256: string;
}
export interface Filters {
  channel: NullableString;
  geo: NullableString;
  date: null;
}
export interface Pagination {
  page: number;
  page_size: number;
  total_rows: number;
  total_pages: number;
}
export interface Totals {
  requested_budget_rub: number;
  source_budget_rub: number;
  selected_budget_rub: number;
  unallocated_budget_rub: number;
  delta_rub: number;
  reconciliation_status: "reconciled";
}
export interface FilteredTotals {
  source_budget_rub: number;
  selected_budget_rub: number;
  delta_rub: number;
}
export interface MediaPlanRow {
  scenario_id: ScenarioId;
  campaign_id: OpaqueId;
  segment: string;
  geo: string;
  channel: string;
  date: null;
  source_budget_rub: number;
  selected_budget_rub: number;
  delta_rub: number;
  delta_pct: NullableNumber;
  source_budget_share: number;
  selected_budget_share: number;
  quality_status: QualityStatus;
  quality_display_text: string;
}
export interface Aggregates {
  /**
   * @minItems 1
   */
  by_channel: [ChannelAggregate, ...ChannelAggregate[]];
  /**
   * @minItems 1
   */
  by_geo: [GeoAggregate, ...GeoAggregate[]];
  /**
   * @minItems 1
   */
  by_geo_channel: [GeoChannelAggregate, ...GeoChannelAggregate[]];
  by_date: UnavailableRows;
  channel_date_matrix: UnavailableRows;
  geo_channel_matrix: ReadyGeoChannelMatrix;
}
export interface ChannelAggregate {
  channel: string;
  source_budget_rub: number;
  selected_budget_rub: number;
  delta_rub: number;
  delta_pct: NullableNumber;
  quality_status: QualityStatus;
  quality_display_text: string;
}
export interface GeoAggregate {
  geo: string;
  source_budget_rub: number;
  selected_budget_rub: number;
  delta_rub: number;
  delta_pct: NullableNumber;
  quality_status: QualityStatus;
  quality_display_text: string;
}
export interface GeoChannelAggregate {
  geo: string;
  channel: string;
  source_budget_rub: number;
  selected_budget_rub: number;
  delta_rub: number;
  delta_pct: NullableNumber;
  quality_status: QualityStatus;
  quality_display_text: string;
}
export interface UnavailableRows {
  status: "unavailable";
  display_text: string;
  rows: null;
}
export interface ReadyGeoChannelMatrix {
  status: "ready";
  display_text: string;
  /**
   * @minItems 1
   */
  rows: [GeoChannelAggregate, ...GeoChannelAggregate[]];
}
export interface Map {
  status: "unavailable";
  display_text: string;
  geo_points: null;
  coordinate_catalog_version: null;
}
export interface ArtifactAvailability {
  status: "unavailable";
  display_text: string;
  artifact: null;
}
export interface Limitation {
  code: string;
  display_text: string;
}
