/* Generated from ../../contracts/validation_result_v2.schema.json. Do not edit manually. */

export type GeoPoint = CanonicalGeoPoint | UnavailableGeoPoint;

export interface ValidationResultV2 {
  contract_name: "validation_result_v2";
  schema_version: "2.0.0";
  validation_id: string;
  status: "passed" | "warning" | "failed" | "unavailable";
  job_creation_allowed: boolean;
  file_validation: {
    status: "passed" | "warning" | "failed" | "unavailable";
    rows_n: number;
    campaigns_n: number;
    geographies_n: number;
    channels_n: number;
    requested_budget_rub: number;
    blocking_errors_n: number;
    warnings_n: number;
    checks: {
      code: string;
      status: "passed" | "warning" | "failed" | "unavailable";
      display_text: string;
    }[];
  };
  federal_allocation: {
    status: "none" | "available" | "error";
    title: string | null;
    description: string | null;
    policy_version: string | null;
    package_id: string | null;
    source_rows_count: number;
    source_budget_rub: number;
    allocated_budget_rub: number;
    difference_rub: number;
    geo_count: number | null;
    declared_geo_count: number | null;
    ready_geo_count: number | null;
    excluded_geo_count: number | null;
    denominator_policy_version: string | null;
    lmax: number | null;
    required_period_start: string | null;
    required_period_end: string | null;
    method_display_name: string | null;
    channels: ChannelIdentity[];
    business_directions: string[];
    mixed_local_overlap: boolean;
    information: StatusMessage[];
    warnings: StatusMessage[];
    errors: StatusMessage[];
    breakdown: {
      business_direction: string;
      channels: ChannelIdentity[];
      source_rows_count: number;
      source_budget_rub: number;
      allocated_budget_rub: number;
      difference_rub: number;
      geo_count: number | null;
      declared_geo_count: number | null;
      ready_geo_count: number | null;
      excluded_geo_count: number | null;
      period_start: string | null;
      period_end: string | null;
    }[];
  };
  model_limitations: {
    target: "turnover";
    channel_id: string;
    channel_display_name: string;
    limitation_type: string;
    affected_geos_n: number;
    affected_geos: string[];
    severity: "information" | "warning" | "manual_review" | "blocking";
    allowed_use: "primary" | "caution" | "diagnostic" | "unsupported" | "unavailable";
    blocks_calculation: boolean;
    what: string;
    why: string;
    recommended_action: string;
  }[];
  map_coverage: BudgetCoverage;
  geo_points: GeoPoint[];
}
export interface ChannelIdentity {
  channel_id: string;
  channel_display_name: string;
}
export interface StatusMessage {
  code: string;
  display_text: string;
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
export interface CanonicalGeoPoint {
  geo_id: string;
  geo_display_name: string;
  input_geo_name: string;
  canonical_geo_id: string;
  canonical_geo_display_name: string;
  normalization_status: "canonical" | "alias";
  normalization_rule: string;
  latitude: number;
  longitude: number;
  coordinates_status: "canonical";
  region_id: string;
  region_display_name: string;
  budget_rub: number;
  budget_share: number | null;
  channels: {
    channel_id: string;
    channel_display_name: string;
  }[];
  has_model_limitations: boolean;
  model_limitations_n: number;
}
export interface UnavailableGeoPoint {
  geo_id: string;
  geo_display_name: string;
  input_geo_name: string;
  canonical_geo_id: null;
  canonical_geo_display_name: null;
  normalization_status: "unknown" | "ambiguous";
  normalization_rule: string;
  latitude: null;
  longitude: null;
  coordinates_status: "unavailable";
  region_id: null;
  region_display_name: null;
  budget_rub: number;
  budget_share: number | null;
  channels: {
    channel_id: string;
    channel_display_name: string;
  }[];
  has_model_limitations: boolean;
  model_limitations_n: number;
}
