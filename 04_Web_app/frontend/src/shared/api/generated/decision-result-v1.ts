/* Generated from ../../contracts/decision_result_v1.schema.json. Do not edit manually. */

export type OpaqueId = string;
export type Sha256 = string;
export type StringArray = string[];
export type NullableQuantileMetric = QuantileMetric | null;
export type NullableNumber = number | null;
export type CalculationStatus = Status & {
  code?: "calculated" | "partially_calculated" | "not_calculated";
  [k: string]: unknown;
};
export type CellSupportStatus = Status & {
  code?: "within_p95" | "between_p95_p99" | "above_p99_within_robust_upper" | "above_robust_upper" | "not_evaluated";
  [k: string]: unknown;
};
export type OptimizerStatus = Status & {
  code?: "best_safe_available" | "partial_safe_available" | "no_safe_candidate" | "gate_policy_blocked" | "not_run";
  [k: string]: unknown;
};
export type QualityStatus = Status & {
  code?:
    | "reliable"
    | "elevated_uncertainty"
    | "manual_review_required"
    | "not_for_automatic_reallocation"
    | "not_calculated";
  [k: string]: unknown;
};
export type NullableFraction = number | null;
export type NullableInteger = number | null;
export type Scenario6RunStatus = Status & {
  code?:
    | "completed_best_safe"
    | "completed_partial_safe"
    | "completed_no_safe_candidate"
    | "gate_policy_blocked"
    | "not_run";
  [k: string]: unknown;
};
export type NullableOpaqueId = OpaqueId | null;
export type RecommendationType = Status & {
  code?:
    | "keep_uploaded_plan"
    | "reallocate_for_reliability"
    | "reallocate_for_effect"
    | "partial_safe_plan"
    | "manual_review";
  [k: string]: unknown;
};
export type PlanStatus = Status & {
  code?: "recommended_media_plan" | "full_plan_partial_model_coverage" | "partial_safe_plan" | "no_automatic_plan";
  [k: string]: unknown;
};
export type CampaignScaleStatus = Status & {
  code?:
    | "within_historical_p95"
    | "between_historical_p95_p99"
    | "between_historical_p99_and_robust_upper"
    | "above_historical_robust_upper"
    | "benchmark_unavailable";
  [k: string]: unknown;
};
export type BusinessDecisionStatus = Status & {
  code?:
    "allocation_only" | "manual_review_required" | "meets_business_hurdle" | "below_business_hurdle" | "not_evaluated";
  [k: string]: unknown;
};

export interface X5MMMDecisionResultV1 {
  contract_name: "decision_result_v1";
  schema_version: "1.0.0";
  result_id: OpaqueId;
  result_origin: "verified_optimizer_artifacts" | "sanitized_fixture";
  created_at_utc: string;
  job: JobLineage;
  model: ModelLineage;
  policies: PolicyLineage;
  /**
   * @minItems 1
   */
  campaign_results: [CampaignResult, ...CampaignResult[]];
  /**
   * @minItems 1
   */
  artifacts: [ArtifactReference, ...ArtifactReference[]];
  warnings: Warning[];
}
export interface JobLineage {
  job_id: OpaqueId;
  source_run_id: string;
  job_type: "forecast_optimizer_report";
  started_at_utc: string;
  finished_at_utc: string;
  workflow_config_sha256: Sha256;
  input_flighting_sha256: Sha256;
  adapter_name: "optimizer_result_adapter";
  adapter_version: "1.0.0";
  adapter_sha256: Sha256;
}
export interface ModelLineage {
  registry_channel: string;
  registry_event_id: string;
  package_id: string;
  package_fingerprint: Sha256;
  package_manifest_sha256: Sha256;
  activation_status: string;
  production_blockers: StringArray;
}
export interface PolicyLineage {
  optimizer_policy_id: string;
  optimizer_policy_sha256: Sha256;
  business_policy_id: string;
  business_policy_sha256: Sha256;
  business_decision_mode: string;
  search_seed: number;
  final_seed: number;
}
export interface CampaignResult {
  campaign_id: OpaqueId;
  passport: CampaignPassport;
  budget: BudgetReconciliation;
  /**
   * @minItems 6
   * @maxItems 6
   */
  scenarios: [ScenarioResult, ScenarioResult, ScenarioResult, ScenarioResult, ScenarioResult, ScenarioResult];
  scenario6: Scenario6Audit;
  recommendation: Recommendation;
  recommended_allocation: AllocationLine[];
  statuses: DecisionStatuses;
  quality: QualitySummary;
  warnings: Warning[];
}
export interface CampaignPassport {
  campaign_name: string;
  source_campaign_name: string;
  segments: StringArray;
  source_start_date: string;
  source_end_date: string;
  model_start_date: string;
  model_end_date: string;
  source_active_days: number;
  model_active_days: number;
  source_channels: StringArray;
  modeled_channels: StringArray;
  unmodeled_channels: StringArray;
  geographies: StringArray;
  creatives: StringArray;
}
export interface BudgetReconciliation {
  uploaded_budget_rub: number;
  model_input_budget_rub: number;
  calculated_budget_rub: number;
  unmodeled_budget_rub: number;
  unallocated_budget_rub: number;
  model_coverage_share: number;
}
export interface ScenarioResult {
  scenario_id: "S01" | "S02" | "S03" | "S04" | "S05" | "S06";
  name: string;
  description: string;
  available: boolean;
  requested_budget_rub: number;
  allocated_budget_rub: number;
  unallocated_budget_rub: number;
  metrics: ScenarioMetrics;
  calculation_status: CalculationStatus;
  cell_support_status: CellSupportStatus;
  optimizer_status: OptimizerStatus;
  support: SupportSummary;
  quality: QualitySummary;
  paired_comparison: PairedComparison | null;
}
export interface ScenarioMetrics {
  incremental_turnover: NullableQuantileMetric;
  roas_p50: NullableNumber;
  incremental_orders: NullableQuantileMetric;
  avg_basket_bridge: NullableQuantileMetric;
}
export interface QuantileMetric {
  unit: "RUB" | "orders";
  p10: number;
  p50: number;
  p90: number;
}
export interface Status {
  code: string;
  display_text: string;
}
export interface SupportSummary {
  elevated_warnings: number;
  strong_warnings: number;
  hard_warnings: number;
  policy_violations: number;
}
export interface QualitySummary {
  status: QualityStatus;
  explanation: string;
  coverage_share: NullableFraction;
  uncertainty_width_share: number | null;
}
export interface PairedComparison {
  delta_incremental_turnover: QuantileMetric;
  probability_gt_zero: NullableFraction;
  probability_noninferior: NullableFraction;
  moved_budget_rub: number | null;
  posterior_draws: NullableInteger;
}
export interface Scenario6Audit {
  run_status: Scenario6RunStatus;
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
  best_raw_candidate_id: NullableOpaqueId;
  best_safe_candidate_id: NullableOpaqueId;
  explanation: string;
}
export interface Recommendation {
  scenario_id: "S01" | "S02" | "S03" | "S04" | "S05" | "S06";
  scenario_name: string;
  candidate_id: OpaqueId;
  recommendation_type: RecommendationType;
  reason: string;
  plan_status: PlanStatus;
  optimizer_available: boolean;
  metrics: ScenarioMetrics;
}
export interface AllocationLine {
  segment: string;
  geo: string;
  channel: string;
  budget_rub: number;
  budget_share: number;
  allocation_note: string;
}
export interface DecisionStatuses {
  calculation_status: CalculationStatus;
  campaign_scale_status: CampaignScaleStatus;
  cell_support_status: CellSupportStatus;
  optimizer_status: OptimizerStatus;
  business_decision_status: BusinessDecisionStatus;
}
export interface Warning {
  code: string;
  severity: "info" | "caution" | "manual_review" | "blocking";
  display_text: string;
  scope: string;
  affected_cells: string[];
}
export interface ArtifactReference {
  artifact_id: OpaqueId;
  kind: string;
  display_name: string;
  media_type: string;
  sha256: Sha256;
  size_bytes: number;
  storage_key: string;
}
