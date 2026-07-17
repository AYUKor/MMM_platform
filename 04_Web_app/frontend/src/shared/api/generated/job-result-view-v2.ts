/* Generated from ../../contracts/job_result_view_v2.schema.json. Do not edit manually. */

export type JobResultViewV2 = JobResultViewV21;

export interface JobResultViewV21 {
  contract_name: "job_result_view_v2";
  schema_version: "2.0.0";
  record_origin: "application_runtime" | "sanitized_fixture";
  job_id: string;
  result_id: string;
  source_overview_id: string;
  updated_at_utc: string;
  campaign: {
    campaign_id: string;
    campaign_name: string;
    segments: string[];
    start_date: string;
    end_date: string;
    requested_budget_rub: number;
    channels: Channel[];
    geographies_n: number;
    geographies: Geo[];
  };
  recommendation: {
    decision_status:
      | "recommended_reallocation"
      | "keep_uploaded_plan"
      | "manual_review_required"
      | "no_safe_recommendation"
      | "unavailable";
    review_status: "not_required" | "manual_review_required";
    scenario_id: string | null;
    title: string;
    display_text: string;
    decision_scope_text: string;
  };
  /**
   * @minItems 6
   * @maxItems 6
   */
  scenarios: [Scenario, Scenario, Scenario, Scenario, Scenario, Scenario];
  media_plan: {
    endpoint: string;
    selected_scenario_id: string;
  };
  map: {
    status: "available" | "partial" | "unavailable";
    display_text: string;
    coordinate_catalog_version: string;
    geo_points: GeoPoint[];
  };
  limitations: {
    code: string;
    display_text: string;
  }[];
}
export interface Channel {
  channel_id: string;
  channel_display_name: string;
}
export interface Geo {
  geo_id: string;
  geo_display_name: string;
}
export interface Scenario {
  scenario_id: "S01" | "S02" | "S03" | "S04" | "S05" | "S06";
  name: string;
  description: string;
  scenario_kind: "uploaded_plan" | "benchmark_plan" | "conservative_plan" | "optimized_plan";
  scenario_variant: string | null;
  status: "completed" | "infeasible" | "unavailable";
  is_recommended: boolean;
  decision_status:
    | "recommended_reallocation"
    | "keep_uploaded_plan"
    | "manual_review_required"
    | "no_safe_recommendation"
    | "unavailable";
  review_status: "not_required" | "manual_review_required";
  budget: Budget;
  incremental_turnover: Quantiles;
  roas: {
    allocated_budget: Quantiles;
    requested_budget: Quantiles;
    primary_denominator_kind: "allocated_budget" | "requested_budget";
    primary_denominator_budget_rub: number;
  };
  risk_budget: RiskBudget;
  reliability: {
    status: "within_support" | "controlled_extrapolation" | "high_risk" | "manual_review" | "unavailable";
    display_text: string;
    evidence_codes: string[];
    safe_rank: number | null;
    raw_rank: number | null;
  };
  limiting_constraints: string[];
}
export interface Budget {
  requested_budget_rub: number;
  allocated_budget_rub: number;
  unallocated_budget_rub: number;
  allocation_share: number | null;
}
export interface Quantiles {
  status: "available" | "unavailable";
  unit: string;
  p10: number | null;
  p50: number | null;
  p90: number | null;
  display_text: string;
}
export interface RiskBudget {
  within_support_budget_rub: number;
  within_support_share: number | null;
  controlled_extrapolation_budget_rub: number;
  controlled_extrapolation_share: number | null;
  high_risk_budget_rub: number;
  high_risk_share: number | null;
  within_support_cells_n: number;
  controlled_extrapolation_cells_n: number;
  high_risk_cells_n: number;
}
export interface GeoPoint {
  geo_id: string;
  geo_display_name: string;
  latitude: number | null;
  longitude: number | null;
  coordinates_status: "canonical" | "unavailable";
  region_id?: string | null;
  region_display_name?: string | null;
}
