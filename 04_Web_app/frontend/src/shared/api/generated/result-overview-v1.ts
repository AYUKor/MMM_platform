/* Generated from ../../contracts/result_overview_v1.schema.json. Do not edit manually. */

export type OpaqueId = string;
export type NullableFraction = number | null;
export type NullableNumber = number | null;
export type NullableMetric = QuantileMetric | null;
export type Sha256 = string;

export interface X5MMMResultOverviewV1 {
  contract_name: "result_overview_v1";
  schema_version: "1.0.0";
  overview_adapter_version: "1.0.0";
  overview_id: OpaqueId;
  source_result_id: OpaqueId;
  result_origin: "verified_optimizer_artifacts" | "sanitized_fixture";
  created_at_utc: string;
  /**
   * @minItems 1
   */
  campaigns: [Campaign, ...Campaign[]];
  /**
   * @minItems 1
   */
  artifacts: [Artifact, ...Artifact[]];
  warnings: Warning[];
}
export interface Campaign {
  campaign_id: OpaqueId;
  passport: Passport;
  budget: BudgetReconciliation;
  statuses: {
    calculation_status: Status;
    campaign_scale_status: Status;
    cell_support_status: Status;
    optimizer_status: Status;
    business_decision_status: Status;
  };
  quality: Quality;
  /**
   * @minItems 6
   * @maxItems 6
   */
  scenarios: [Scenario, Scenario, Scenario, Scenario, Scenario, Scenario];
  recommendation: {
    scenario_id: "S01" | "S02" | "S03" | "S04" | "S05" | "S06";
    scenario_name: string;
    recommendation_type: Status;
    reason: string;
    plan_status: Status;
    optimizer_available: boolean;
    metrics: Metrics;
    versus_uploaded_plan: {
      delta_incremental_turnover_p50_rub: NullableNumber;
      delta_incremental_turnover_p50_share: NullableNumber;
      moved_budget_rub: number;
    };
  };
  scenario6: {
    audit: Scenario6Audit;
    best_raw: Candidate | null;
    best_safe: Candidate | null;
    raw_differs_from_safe: boolean;
  };
  /**
   * @minItems 1
   */
  allocation_comparison: [AllocationLine, ...AllocationLine[]];
  warnings: Warning[];
}
export interface Passport {
  campaign_name: string;
  source_campaign_name: string;
  /**
   * @minItems 1
   */
  segments: [string, ...string[]];
  source_start_date: string;
  source_end_date: string;
  model_start_date: string;
  model_end_date: string;
  source_active_days: number;
  model_active_days: number;
  /**
   * @minItems 1
   */
  source_channels: [string, ...string[]];
  modeled_channels: string[];
  unmodeled_channels: string[];
  /**
   * @minItems 1
   */
  geographies: [string, ...string[]];
  creatives: string[];
}
export interface BudgetReconciliation {
  uploaded_budget_rub: number;
  model_input_budget_rub: number;
  calculated_budget_rub: number;
  unmodeled_budget_rub: number;
  unallocated_budget_rub: number;
  model_coverage_share: number;
}
export interface Status {
  code: string;
  display_text: string;
}
export interface Quality {
  status: Status;
  explanation: string;
  coverage_share: NullableFraction;
  uncertainty_width_share: NullableNumber;
}
export interface Scenario {
  scenario_id: "S01" | "S02" | "S03" | "S04" | "S05" | "S06";
  name: string;
  description: string;
  available: boolean;
  budget: {
    requested_budget_rub: number;
    allocated_budget_rub: number;
    unallocated_budget_rub: number;
  };
  metrics: Metrics;
  calculation_status: Status;
  cell_support_status: Status;
  optimizer_status: Status;
  support: Support;
  quality: Quality;
  paired_comparison: PairedComparison | null;
}
export interface Metrics {
  incremental_turnover: NullableMetric;
  turnover_roas: NullableMetric;
  incremental_orders: NullableMetric;
  incremental_orders_usage: "diagnostic_only";
  avg_basket_turnover_bridge: NullableMetric;
}
export interface QuantileMetric {
  unit: "RUB" | "orders" | "ratio" | "turnover_bridge_from_avg_basket_rub";
  p10: number;
  p50: number;
  p90: number;
}
export interface Support {
  elevated_warnings: number;
  strong_warnings: number;
  hard_warnings: number;
  policy_violations: number;
}
export interface PairedComparison {
  delta_incremental_turnover: QuantileMetric;
  probability_gt_zero: NullableFraction;
  probability_noninferior: NullableFraction;
  moved_budget_rub: NullableNumber;
  posterior_draws: number | null;
}
export interface Scenario6Audit {
  run_status: Status;
  method: string;
  attempt_budget: number;
  attempts_evaluated: number;
  kernel_evaluations: number;
  unique_allocations: number;
  candidates_generated: number;
  candidates_scored: number;
  candidates_rejected: number;
  finalists: number;
  search_posterior_draws: number;
  final_posterior_draws: number;
  search_converged: boolean | null;
  search_budget_exhausted: boolean | null;
  best_raw_candidate_id: OpaqueId | null;
  best_safe_candidate_id: OpaqueId | null;
  explanation: string;
}
export interface Candidate {
  candidate_id: OpaqueId;
  evaluation_level: "search_only" | "final_posterior";
  eligible_for_automatic_recommendation: boolean;
  incremental_turnover: NullableMetric;
  turnover_roas: NullableMetric;
  support: Support;
  rejection_reasons: string[];
  explanation: string;
}
export interface AllocationLine {
  segment: string;
  geo: string;
  channel: string;
  uploaded_budget_rub: number;
  recommended_budget_rub: number;
  delta_budget_rub: number;
  uploaded_budget_share: number;
  recommended_budget_share: number;
  action: "increase" | "decrease" | "keep";
  optimizer_policy: string;
  allowed_use: string;
  gate_reason_codes: string[];
}
export interface Warning {
  code: string;
  severity: "info" | "caution" | "manual_review" | "blocking";
  display_text: string;
  scope: string;
  affected_cells: string[];
}
export interface Artifact {
  artifact_id: OpaqueId;
  kind: string;
  display_name: string;
  media_type: string;
  sha256: Sha256;
  size_bytes: number;
  storage_key: string;
  download_path: string;
}
