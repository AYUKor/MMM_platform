/* Generated from ../../contracts/job_result_view_v1.schema.json. Do not edit manually. */

export type OpaqueId = string;
export type ScenarioId = "S01" | "S02" | "S03" | "S04" | "S05" | "S06";
export type NullablePositiveInteger = number | null;
export type NullableNumber = number | null;
export type QualityStatus = "safe" | "caution" | "blocked" | "unavailable";
export type BudgetComparison = BudgetComparison1 & {
  channel?: string;
  geo?: string;
  source_budget_rub: number;
  selected_budget_rub: number;
  delta_rub: number;
  delta_pct: NullableNumber;
  quality_status: QualityStatus;
  quality_display_text: string;
} & BudgetComparison1 & {
    channel?: string;
    geo?: string;
    source_budget_rub: number;
    selected_budget_rub: number;
    delta_rub: number;
    delta_pct: NullableNumber;
    quality_status: QualityStatus;
    quality_display_text: string;
  } & BudgetComparison1 & {
    channel?: string;
    geo?: string;
    source_budget_rub: number;
    selected_budget_rub: number;
    delta_rub: number;
    delta_pct: NullableNumber;
    quality_status: QualityStatus;
    quality_display_text: string;
  } & BudgetComparison1 & {
    channel?: string;
    geo?: string;
    source_budget_rub: number;
    selected_budget_rub: number;
    delta_rub: number;
    delta_pct: NullableNumber;
    quality_status: QualityStatus;
    quality_display_text: string;
  } & BudgetComparison1 & {
    channel?: string;
    geo?: string;
    source_budget_rub: number;
    selected_budget_rub: number;
    delta_rub: number;
    delta_pct: NullableNumber;
    quality_status: QualityStatus;
    quality_display_text: string;
  } & BudgetComparison1 & {
    channel?: string;
    geo?: string;
    source_budget_rub: number;
    selected_budget_rub: number;
    delta_rub: number;
    delta_pct: NullableNumber;
    quality_status: QualityStatus;
    quality_display_text: string;
  };
export type BudgetComparison1 =
  | {
      [k: string]: unknown;
    }
  | {
      [k: string]: unknown;
    }
  | {
      [k: string]: unknown;
    };
export type MetricUnit =
  "RUB" | "orders" | "orders_per_100k_RUB" | "RUB_per_order" | "turnover_bridge_from_avg_basket_rub" | "ratio";
export type NullableString = string | null;

export interface JobResultViewV1 {
  contract_name: "job_result_view_v1";
  schema_version: "1.0.0";
  record_origin: "application_runtime" | "sanitized_fixture";
  job_id: OpaqueId;
  result_id: OpaqueId;
  source_overview_id: OpaqueId;
  updated_at_utc: string;
  campaign: Campaign;
  recommendation: Recommendation;
  overview: Overview;
  /**
   * @minItems 6
   * @maxItems 6
   */
  scenarios: [Scenario, Scenario, Scenario, Scenario, Scenario, Scenario];
  reliability: Reliability;
  warnings: Warning[];
  best_raw: BestRaw;
  media_plan: MediaPlanSummary;
  report: Report;
  /**
   * @minItems 1
   */
  limitations: [Limitation, ...Limitation[]];
}
export interface Campaign {
  campaign_id: OpaqueId;
  campaign_name: string;
  /**
   * @minItems 1
   */
  segments: [string, ...string[]];
  start_date: string;
  end_date: string;
  total_budget_rub: number;
  channels_n: number;
  geographies_n: number;
  model_coverage_share: number;
}
export interface Recommendation {
  status: "recommended" | "no_safe_recommendation" | "unavailable";
  scenario_id: ScenarioId | null;
  title: string;
  display_text: string;
  decision_scope_text: string;
  safe_rank: NullablePositiveInteger;
  raw_rank: NullablePositiveInteger;
  best_safe: BestSafe;
}
export interface BestSafe {
  available: boolean;
  scenario_id: ScenarioId | null;
  safe_rank: NullablePositiveInteger;
  raw_rank: NullablePositiveInteger;
  display_text: string;
}
export interface Overview {
  selected_scenario_id: ScenarioId;
  source_scenario_id: "S01";
  benchmark_scenario_id: "S05";
  /**
   * @minItems 7
   * @maxItems 7
   */
  headline_metrics: [
    HeadlineMetric,
    HeadlineMetric,
    HeadlineMetric,
    HeadlineMetric,
    HeadlineMetric,
    HeadlineMetric,
    HeadlineMetric
  ];
  scenario_range: {
    metric_id: "incremental_turnover_rub";
    unit: "RUB";
    /**
     * @minItems 1
     */
    rows: [RangeRow, ...RangeRow[]];
  };
  /**
   * @minItems 1
   */
  channel_summary: [BudgetComparison, ...BudgetComparison[]];
  /**
   * @minItems 1
   */
  geo_summary: [BudgetComparison, ...BudgetComparison[]];
  /**
   * @minItems 1
   */
  geo_channel_summary: [BudgetComparison, ...BudgetComparison[]];
}
export interface HeadlineMetric {
  metric_id:
    | "incremental_turnover_rub"
    | "incremental_orders"
    | "orders_per_100k_rub"
    | "avg_basket_delta_rub"
    | "total_budget_rub"
    | "reliability_score"
    | "safe_rank";
  title: string;
  status: "available" | "unavailable";
  unit: "RUB" | "orders" | "orders_per_100k_RUB" | "RUB_per_order" | "score_1_10" | "rank";
  p10: NullableNumber;
  p50: NullableNumber;
  p90: NullableNumber;
  value: NullableNumber;
  display_text: string;
}
export interface RangeRow {
  scenario_id: ScenarioId;
  p10: number;
  p50: number;
  p90: number;
  quality_status: QualityStatus;
}
export interface Scenario {
  scenario_id: ScenarioId;
  title: string;
  description: string;
  role: "source" | "control" | "benchmark" | "adaptive";
  status: "completed" | "unavailable" | "failed";
  is_recommended: boolean;
  is_best_safe: boolean;
  is_best_raw: boolean;
  safe_rank: NullablePositiveInteger;
  raw_rank: NullablePositiveInteger;
  quality_status: QualityStatus;
  quality_display_text: string;
  budget: ScenarioBudget;
  metrics: ScenarioMetrics;
  reliability: Reliability;
}
export interface ScenarioBudget {
  requested_budget_rub: number;
  allocated_budget_rub: number;
  unallocated_budget_rub: number;
}
export interface ScenarioMetrics {
  incremental_turnover_rub: QuantileMetric;
  incremental_orders: QuantileMetric;
  orders_per_100k_rub: QuantileMetric;
  avg_basket_delta_rub: QuantileMetric;
  avg_basket_turnover_bridge_rub: QuantileMetric;
  roas: QuantileMetric;
}
export interface QuantileMetric {
  status: "available" | "unavailable";
  unit: MetricUnit;
  p10: NullableNumber;
  p50: NullableNumber;
  p90: NullableNumber;
  usage: "primary" | "diagnostic_only" | "unavailable" | "audit_only";
  display_text: string;
  formula_version: NullableString;
}
export interface Reliability {
  score: null;
  status: "unavailable";
  display_text: string;
  /**
   * @minItems 6
   * @maxItems 6
   */
  components: [
    ReliabilityComponent,
    ReliabilityComponent,
    ReliabilityComponent,
    ReliabilityComponent,
    ReliabilityComponent,
    ReliabilityComponent
  ];
}
export interface ReliabilityComponent {
  component_id:
    | "historical_support"
    | "model_support"
    | "extrapolation"
    | "posterior_uncertainty"
    | "business_constraints"
    | "data_completeness";
  title: string;
  status: "good" | "caution" | "poor" | "unavailable";
  score: null;
  observed_value: number | string | null;
  display_text: string;
}
export interface Warning {
  code: string;
  severity: "info" | "caution" | "manual_review" | "blocking";
  title: string;
  display_text: string;
  recommended_action: string;
  scope: "campaign" | "selected_scenario" | "recommendation" | "scenario6";
}
export interface BestRaw {
  available: boolean;
  scenario_id: ScenarioId | null;
  raw_rank: NullablePositiveInteger;
  safe_rank: NullablePositiveInteger;
  reason_not_recommended: NullableString;
  metrics: AuditMetric | null;
  blocking_cells_status: "available" | "unavailable" | "not_applicable";
  blocking_cells: BlockingCell[];
}
export interface AuditMetric {
  incremental_turnover_rub: QuantileMetric;
  roas: QuantileMetric;
}
export interface BlockingCell {
  segment: string;
  geo: string;
  channel: string;
  reason: string;
}
export interface MediaPlanSummary {
  endpoint: string;
  selected_scenario_id: ScenarioId;
  grain: "geo_channel_total";
  /**
   * @minItems 6
   * @maxItems 6
   */
  scenario_options: [ScenarioOption, ScenarioOption, ScenarioOption, ScenarioOption, ScenarioOption, ScenarioOption];
  daily_plan: {
    status: "unavailable";
    display_text: string;
  };
  map: Map;
  working_media_plan: ArtifactAvailability;
}
export interface ScenarioOption {
  scenario_id: ScenarioId;
  title: string;
  status: "completed" | "unavailable" | "failed";
}
export interface Map {
  status: "unavailable";
  display_text: string;
  geo_points: null;
  coordinate_catalog_version: null;
}
export interface ArtifactAvailability {
  status: "ready" | "unavailable";
  display_text: string;
  artifact: Artifact | null;
}
export interface Artifact {
  artifact_id: OpaqueId;
  display_name: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  download_path: string;
}
export interface Report {
  status: "ready" | "failed" | "unavailable";
  display_text: string;
  generated_at_utc: string | null;
  artifact: Artifact | null;
  sheets: Sheet[];
  working_media_plan: ArtifactAvailability;
}
export interface Sheet {
  sheet_name: string;
  title: string;
  description: NullableString;
}
export interface Limitation {
  code: string;
  display_text: string;
}
