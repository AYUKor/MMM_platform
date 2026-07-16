import type {
  Artifact,
  ArtifactAvailability,
  BudgetComparison,
  JobResultViewV1,
  QuantileMetric,
  Reliability,
  Scenario,
  ScenarioId,
} from "./generated/job-result-view-v1";
import type {
  ScenarioMediaPlanV1,
} from "./generated/scenario-media-plan-v1";
import { appEnv } from "../config/env";

const SCENARIO_IDS = ["S01", "S02", "S03", "S04", "S05", "S06"] as const;
const SCENARIO_ROLES = ["source", "control", "control", "control", "benchmark", "adaptive"] as const;
const QUALITY_STATUSES = ["safe", "caution", "blocked", "unavailable"] as const;
const RESULT_STATUSES = ["completed", "unavailable", "failed"] as const;
const COMPONENT_IDS = [
  "historical_support",
  "model_support",
  "extrapolation",
  "posterior_uncertainty",
  "business_constraints",
  "data_completeness",
] as const;
const HEADLINE_IDS = [
  "incremental_turnover_rub",
  "incremental_orders",
  "orders_per_100k_rub",
  "avg_basket_delta_rub",
  "total_budget_rub",
  "reliability_score",
  "safe_rank",
] as const;
const METRIC_SEMANTICS = {
  incremental_turnover_rub: ["RUB", "primary", null],
  incremental_orders: ["orders", "diagnostic_only", null],
  orders_per_100k_rub: [
    "orders_per_100k_RUB",
    "diagnostic_only",
    "orders_quantile_divided_by_deterministic_budget_v1",
  ],
  avg_basket_delta_rub: ["RUB_per_order", "unavailable", null],
  avg_basket_turnover_bridge_rub: [
    "turnover_bridge_from_avg_basket_rub",
    "diagnostic_only",
    null,
  ],
  roas: ["ratio", "primary", null],
} as const;

const RESULT_KEYS = [
  "contract_name", "schema_version", "record_origin", "job_id", "result_id",
  "source_overview_id", "updated_at_utc", "campaign", "recommendation", "overview",
  "scenarios", "reliability", "warnings", "best_raw", "media_plan", "report",
  "limitations",
] as const;
const CAMPAIGN_KEYS = [
  "campaign_id", "campaign_name", "segments", "start_date", "end_date",
  "total_budget_rub", "channels_n", "geographies_n", "model_coverage_share",
] as const;
const RECOMMENDATION_KEYS = [
  "status", "scenario_id", "title", "display_text", "decision_scope_text",
  "safe_rank", "raw_rank", "best_safe",
] as const;
const BEST_SAFE_KEYS = [
  "available", "scenario_id", "safe_rank", "raw_rank", "display_text",
] as const;
const OVERVIEW_KEYS = [
  "selected_scenario_id", "source_scenario_id", "benchmark_scenario_id",
  "headline_metrics", "scenario_range", "channel_summary", "geo_summary",
  "geo_channel_summary",
] as const;
const HEADLINE_KEYS = [
  "metric_id", "title", "status", "unit", "p10", "p50", "p90", "value",
  "display_text",
] as const;
const RANGE_KEYS = ["metric_id", "unit", "rows"] as const;
const RANGE_ROW_KEYS = ["scenario_id", "p10", "p50", "p90", "quality_status"] as const;
const SCENARIO_KEYS = [
  "scenario_id", "title", "description", "role", "status", "is_recommended",
  "is_best_safe", "is_best_raw", "safe_rank", "raw_rank", "quality_status",
  "quality_display_text", "budget", "metrics", "reliability",
] as const;
const SCENARIO_BUDGET_KEYS = [
  "requested_budget_rub", "allocated_budget_rub", "unallocated_budget_rub",
] as const;
const SCENARIO_METRIC_KEYS = Object.keys(METRIC_SEMANTICS);
const QUANTILE_KEYS = [
  "status", "unit", "p10", "p50", "p90", "usage", "display_text",
  "formula_version",
] as const;
const RELIABILITY_KEYS = ["score", "status", "display_text", "components"] as const;
const COMPONENT_KEYS = [
  "component_id", "title", "status", "score", "observed_value", "display_text",
] as const;
const WARNING_KEYS = [
  "code", "severity", "title", "display_text", "recommended_action", "scope",
] as const;
const BEST_RAW_KEYS = [
  "available", "scenario_id", "raw_rank", "safe_rank", "reason_not_recommended",
  "metrics", "blocking_cells_status", "blocking_cells",
] as const;
const AUDIT_METRIC_KEYS = ["incremental_turnover_rub", "roas"] as const;
const BLOCKING_CELL_KEYS = ["segment", "geo", "channel", "reason"] as const;
const MEDIA_SUMMARY_KEYS = [
  "endpoint", "selected_scenario_id", "grain", "scenario_options", "daily_plan",
  "map", "working_media_plan",
] as const;
const SCENARIO_OPTION_KEYS = ["scenario_id", "title", "status"] as const;
const UNAVAILABLE_TEXT_KEYS = ["status", "display_text"] as const;
const MAP_KEYS = [
  "status", "display_text", "geo_points", "coordinate_catalog_version",
] as const;
const ARTIFACT_AVAILABILITY_KEYS = ["status", "display_text", "artifact"] as const;
const ARTIFACT_KEYS = [
  "artifact_id", "display_name", "media_type", "size_bytes", "sha256",
  "download_path",
] as const;
const REPORT_KEYS = [
  "status", "display_text", "generated_at_utc", "artifact", "sheets",
  "working_media_plan",
] as const;
const SHEET_KEYS = ["sheet_name", "title", "description"] as const;
const LIMITATION_KEYS = ["code", "display_text"] as const;
const CHANNEL_BUDGET_KEYS = [
  "channel", "source_budget_rub", "selected_budget_rub", "delta_rub", "delta_pct",
  "quality_status", "quality_display_text",
] as const;
const GEO_BUDGET_KEYS = [
  "geo", "source_budget_rub", "selected_budget_rub", "delta_rub", "delta_pct",
  "quality_status", "quality_display_text",
] as const;
const GEO_CHANNEL_BUDGET_KEYS = [
  "geo", "channel", "source_budget_rub", "selected_budget_rub", "delta_rub",
  "delta_pct", "quality_status", "quality_display_text",
] as const;

const PLAN_KEYS = [
  "contract_name", "schema_version", "record_origin", "job_id", "result_id",
  "campaign_id", "scenario", "source_artifact", "grain", "filters", "pagination",
  "totals", "filtered_totals", "rows", "aggregates", "map", "working_media_plan",
  "limitations", "updated_at_utc",
] as const;
const PLAN_SCENARIO_KEYS = [
  "scenario_id", "title", "status", "is_selected", "safe_rank", "raw_rank",
  "quality_status", "quality_display_text",
] as const;
const SOURCE_ARTIFACT_KEYS = ["artifact_id", "kind", "sha256"] as const;
const FILTER_KEYS = ["channel", "geo", "date"] as const;
const PAGINATION_KEYS = ["page", "page_size", "total_rows", "total_pages"] as const;
const TOTAL_KEYS = [
  "requested_budget_rub", "source_budget_rub", "selected_budget_rub",
  "unallocated_budget_rub", "delta_rub", "reconciliation_status",
] as const;
const FILTERED_TOTAL_KEYS = ["source_budget_rub", "selected_budget_rub", "delta_rub"] as const;
const PLAN_ROW_KEYS = [
  "scenario_id", "campaign_id", "segment", "geo", "channel", "date",
  "source_budget_rub", "selected_budget_rub", "delta_rub", "delta_pct",
  "source_budget_share", "selected_budget_share", "quality_status",
  "quality_display_text",
] as const;
const AGGREGATE_KEYS = [
  "by_channel", "by_geo", "by_geo_channel", "by_date", "channel_date_matrix",
  "geo_channel_matrix",
] as const;
const UNAVAILABLE_ROWS_KEYS = ["status", "display_text", "rows"] as const;
const READY_MATRIX_KEYS = ["status", "display_text", "rows"] as const;
const PLAN_ARTIFACT_AVAILABILITY_KEYS = ["status", "display_text", "artifact"] as const;
const ERROR_PAYLOAD_KEYS = ["error"] as const;
const ERROR_KEYS = ["code", "display_text", "retryable", "user_action"] as const;

const OPAQUE_ID_RE = /^[a-z][a-z0-9_]*_[0-9a-f]{12,64}$/;
const SHA256_RE = /^[0-9a-f]{64}$/;
const WARNING_CODE_RE = /^[a-z][a-z0-9_]+$/;
const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const ISO_DATETIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const ABSOLUTE_PATH_RE = /^(?:\/|[A-Za-z]:[\\/]|file:\/\/)/i;
const DOWNLOAD_PATH_RE = /^\/api\/v1\/artifacts\/([a-z][a-z0-9_]*_[0-9a-f]{12,64})\/download$/;

type JsonRecord = Record<string, unknown>;

export interface ScenarioMediaPlanQuery {
  scenarioId: ScenarioId;
  page?: number;
  pageSize?: number;
  channel?: string | null;
  geo?: string | null;
}

export interface NormalizedScenarioMediaPlanQuery {
  scenarioId: ScenarioId;
  page: number;
  pageSize: number;
  channel: string | null;
  geo: string | null;
}

export class JobResultNotFoundError extends Error {
  readonly status = 404;
  constructor() {
    super("Результат не найден.");
    this.name = "JobResultNotFoundError";
  }
}

export class JobResultNotReadyError extends Error {
  readonly status = 404;
  readonly retryable = true;
  constructor() {
    super("Результат еще не готов.");
    this.name = "JobResultNotReadyError";
  }
}

export class JobResultInconsistentError extends Error {
  readonly status = 409;
  constructor() {
    super("Данные результата временно не согласованы.");
    this.name = "JobResultInconsistentError";
  }
}

export class JobResultUnavailableError extends Error {
  readonly status = 503;
  constructor() {
    super("Результат временно недоступен.");
    this.name = "JobResultUnavailableError";
  }
}

export class JobResultRequestError extends Error {
  readonly status: number | null;
  constructor(status: number | null = null) {
    super("Не удалось получить результат расчета.");
    this.name = "JobResultRequestError";
    this.status = status;
  }
}

export class UnsupportedJobResultContractError extends Error {
  readonly status: number | null;
  constructor(status: number | null = null) {
    super("Сервис вернул неподдерживаемый формат результата.");
    this.name = "UnsupportedJobResultContractError";
    this.status = status;
  }
}

export class MediaPlanQueryUnsupportedError extends Error {
  readonly status = 422;
  constructor() {
    super("Выбранные параметры медиаплана не поддерживаются.");
    this.name = "MediaPlanQueryUnsupportedError";
  }
}

export class MediaPlanUnavailableError extends Error {
  readonly status = 503;
  constructor() {
    super("Медиаплан временно недоступен.");
    this.name = "MediaPlanUnavailableError";
  }
}

export class MediaPlanRequestError extends Error {
  readonly status: number | null;
  constructor(status: number | null = null) {
    super("Не удалось получить медиаплан.");
    this.name = "MediaPlanRequestError";
    this.status = status;
  }
}

export class UnsupportedScenarioMediaPlanContractError extends Error {
  readonly status: number | null;
  constructor(status: number | null = null) {
    super("Сервис вернул неподдерживаемый формат медиаплана.");
    this.name = "UnsupportedScenarioMediaPlanContractError";
    this.status = status;
  }
}

function failResult(): never {
  throw new UnsupportedJobResultContractError();
}

function failPlan(): never {
  throw new UnsupportedScenarioMediaPlanContractError();
}

function isRecord(value: unknown): value is JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function productErrorCode(value: unknown): string | null {
  if (!isRecord(value) || !hasExactKeys(value, ERROR_PAYLOAD_KEYS) || !isRecord(value.error) ||
    !hasExactKeys(value.error, ERROR_KEYS) || !isText(value.error.code) ||
    !isText(value.error.display_text) || typeof value.error.retryable !== "boolean" ||
    !isText(value.error.user_action)) return null;
  return value.error.code;
}

function hasExactKeys(value: JsonRecord, keys: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.length && keys.every((key) => key in value);
}

function isText(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isNonNegative(value: unknown): value is number {
  return isFiniteNumber(value) && value >= 0;
}

function isInteger(value: unknown): value is number {
  return isFiniteNumber(value) && Number.isInteger(value);
}

function isPositiveInteger(value: unknown): value is number {
  return isInteger(value) && value >= 1;
}

function isNonNegativeInteger(value: unknown): value is number {
  return isInteger(value) && value >= 0;
}

function isNullablePositiveInteger(value: unknown): value is number | null {
  return value === null || isPositiveInteger(value);
}

function isEnum<T extends readonly string[]>(value: unknown, values: T): value is T[number] {
  return typeof value === "string" && values.includes(value as T[number]);
}

function isScenarioId(value: unknown): value is ScenarioId {
  return isEnum(value, SCENARIO_IDS);
}

function isOpaqueId(value: unknown): value is string {
  return typeof value === "string" && OPAQUE_ID_RE.test(value);
}

function isIsoDate(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = ISO_DATE_RE.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day;
}

function isIsoDateTime(value: unknown): value is string {
  return typeof value === "string" && ISO_DATETIME_RE.test(value) && Number.isFinite(Date.parse(value));
}

function nearlyEqual(left: number, right: number, tolerance = 0.01): boolean {
  return Math.abs(left - right) <= tolerance;
}

function uniqueStrings(values: unknown, allowEmpty = false): values is string[] {
  return Array.isArray(values) &&
    (allowEmpty || values.length > 0) &&
    values.every(isText) &&
    new Set(values).size === values.length;
}

function hasForbiddenPath(value: unknown, trail: readonly string[] = []): boolean {
  if (typeof value === "string" && ABSOLUTE_PATH_RE.test(value)) {
    const field = trail.at(-1);
    if (field === "download_path" && DOWNLOAD_PATH_RE.test(value)) return false;
    if (field === "endpoint" && /^\/api\/v1\/jobs\/[a-z][a-z0-9_]*_[0-9a-f]{12,64}\/media-plan$/.test(value)) return false;
    return true;
  }
  if (Array.isArray(value)) return value.some((item, index) => hasForbiddenPath(item, [...trail, String(index)]));
  if (isRecord(value)) return Object.entries(value).some(([key, item]) => hasForbiddenPath(item, [...trail, key]));
  return false;
}

function isQuantileMetric(
  value: unknown,
  unit: string,
  usage: string,
  formulaVersion: string | null,
): value is QuantileMetric {
  if (!isRecord(value) || !hasExactKeys(value, QUANTILE_KEYS)) return false;
  if (
    (value.status !== "available" && value.status !== "unavailable") ||
    value.unit !== unit || value.usage !== usage || value.formula_version !== formulaVersion ||
    !isText(value.display_text)
  ) return false;
  const quantiles = [value.p10, value.p50, value.p90];
  if (value.status === "unavailable") return quantiles.every((item) => item === null);
  return quantiles.every(isFiniteNumber) &&
    (value.p10 as number) <= (value.p50 as number) &&
    (value.p50 as number) <= (value.p90 as number);
}

function isReliability(value: unknown): value is Reliability {
  if (!isRecord(value) || !hasExactKeys(value, RELIABILITY_KEYS)) return false;
  if (value.score !== null || value.status !== "unavailable" || !isText(value.display_text)) return false;
  if (!Array.isArray(value.components) || value.components.length !== COMPONENT_IDS.length) return false;
  return value.components.every((component, index) =>
    isRecord(component) && hasExactKeys(component, COMPONENT_KEYS) &&
    component.component_id === COMPONENT_IDS[index] && isText(component.title) &&
    isEnum(component.status, ["good", "caution", "poor", "unavailable"] as const) &&
    (component.component_id !== "posterior_uncertainty" || component.status === "unavailable") &&
    component.score === null &&
    (component.observed_value === null || isFiniteNumber(component.observed_value) || isText(component.observed_value)) &&
    isText(component.display_text),
  );
}

function isBudgetComparison(
  value: unknown,
  dimension: "channel" | "geo" | "geo_channel",
): value is BudgetComparison {
  const keys = dimension === "channel" ? CHANNEL_BUDGET_KEYS : dimension === "geo" ? GEO_BUDGET_KEYS : GEO_CHANNEL_BUDGET_KEYS;
  if (!isRecord(value) || !hasExactKeys(value, keys)) return false;
  if (
    (dimension !== "channel" && !isText(value.geo)) ||
    (dimension !== "geo" && !isText(value.channel)) ||
    !isNonNegative(value.source_budget_rub) || !isNonNegative(value.selected_budget_rub) ||
    !isFiniteNumber(value.delta_rub) || !isEnum(value.quality_status, QUALITY_STATUSES) ||
    !isText(value.quality_display_text)
  ) return false;
  const expectedDelta = value.selected_budget_rub - value.source_budget_rub;
  if (!nearlyEqual(value.delta_rub, expectedDelta)) return false;
  if (value.source_budget_rub === 0) return value.delta_pct === null;
  return isFiniteNumber(value.delta_pct) && nearlyEqual(value.delta_pct, expectedDelta / value.source_budget_rub * 100, 1e-6);
}

function isArtifact(value: unknown): value is Artifact {
  if (!isRecord(value) || !hasExactKeys(value, ARTIFACT_KEYS)) return false;
  const pathMatch = typeof value.download_path === "string" ? DOWNLOAD_PATH_RE.exec(value.download_path) : null;
  return isOpaqueId(value.artifact_id) && isText(value.display_name) && isText(value.media_type) &&
    isNonNegativeInteger(value.size_bytes) && typeof value.sha256 === "string" && SHA256_RE.test(value.sha256) &&
    pathMatch !== null && pathMatch[1] === value.artifact_id;
}

function isArtifactAvailability(value: unknown): value is ArtifactAvailability {
  if (!isRecord(value) || !hasExactKeys(value, ARTIFACT_AVAILABILITY_KEYS) || !isText(value.display_text)) return false;
  if (value.status === "ready") return isArtifact(value.artifact);
  return value.status === "unavailable" && value.artifact === null;
}

function isScenario(value: unknown, index: number): value is Scenario {
  if (!isRecord(value) || !hasExactKeys(value, SCENARIO_KEYS)) return false;
  if (
    value.scenario_id !== SCENARIO_IDS[index] || value.role !== SCENARIO_ROLES[index] ||
    !isText(value.title) || !isText(value.description) || !isEnum(value.status, RESULT_STATUSES) ||
    typeof value.is_recommended !== "boolean" || typeof value.is_best_safe !== "boolean" ||
    typeof value.is_best_raw !== "boolean" || !isNullablePositiveInteger(value.safe_rank) ||
    !isNullablePositiveInteger(value.raw_rank) || !isEnum(value.quality_status, QUALITY_STATUSES) ||
    !isText(value.quality_display_text) || !isRecord(value.budget) ||
    !hasExactKeys(value.budget, SCENARIO_BUDGET_KEYS) ||
    !isNonNegative(value.budget.requested_budget_rub) || !isNonNegative(value.budget.allocated_budget_rub) ||
    !isNonNegative(value.budget.unallocated_budget_rub) ||
    !nearlyEqual(value.budget.allocated_budget_rub + value.budget.unallocated_budget_rub, value.budget.requested_budget_rub, 1) ||
    !isRecord(value.metrics) || !hasExactKeys(value.metrics, SCENARIO_METRIC_KEYS) ||
    !isReliability(value.reliability)
  ) return false;
  for (const [metricId, semantics] of Object.entries(METRIC_SEMANTICS)) {
    if (!isQuantileMetric(value.metrics[metricId], semantics[0], semantics[1], semantics[2])) return false;
  }
  const metrics = value.metrics as unknown as Record<string, QuantileMetric>;
  if (metrics.avg_basket_delta_rub.status !== "unavailable") return false;
  if (value.status === "completed") return metrics.incremental_turnover_rub.status === "available";
  return Object.values(metrics).every((metric) => metric.status === "unavailable");
}

function validateResultOverview(value: JsonRecord, scenarios: readonly Scenario[]): void {
  if (!hasExactKeys(value, OVERVIEW_KEYS) || !isScenarioId(value.selected_scenario_id) ||
    value.source_scenario_id !== "S01" || value.benchmark_scenario_id !== "S05") failResult();
  if (!Array.isArray(value.headline_metrics) || value.headline_metrics.length !== HEADLINE_IDS.length) failResult();
  const headlines = value.headline_metrics as unknown[];
  headlines.forEach((headline, index) => {
    if (!isRecord(headline) || !hasExactKeys(headline, HEADLINE_KEYS) ||
      headline.metric_id !== HEADLINE_IDS[index] || !isText(headline.title) ||
      (headline.status !== "available" && headline.status !== "unavailable") || !isText(headline.display_text) ||
      ![headline.p10, headline.p50, headline.p90, headline.value].every((item) => item === null || isFiniteNumber(item))) failResult();
    const expectedUnits = ["RUB", "orders", "orders_per_100k_RUB", "RUB_per_order", "RUB", "score_1_10", "rank"];
    if (headline.unit !== expectedUnits[index]) failResult();
    if (index <= 3) {
      if (headline.value !== null) failResult();
      const values = [headline.p10, headline.p50, headline.p90];
      if (headline.status === "available") {
        if (!values.every(isFiniteNumber) || (headline.p10 as number) > (headline.p50 as number) || (headline.p50 as number) > (headline.p90 as number)) failResult();
      } else if (!values.every((item) => item === null)) failResult();
    } else {
      if (![headline.p10, headline.p50, headline.p90].every((item) => item === null)) failResult();
      if ((headline.status === "available") !== isFiniteNumber(headline.value)) failResult();
    }
  });
  if (!isRecord(value.scenario_range) || !hasExactKeys(value.scenario_range, RANGE_KEYS) ||
    value.scenario_range.metric_id !== "incremental_turnover_rub" || value.scenario_range.unit !== "RUB" ||
    !Array.isArray(value.scenario_range.rows) || value.scenario_range.rows.length === 0) failResult();
  const expectedRangeIds = scenarios.filter((scenario) => scenario.metrics.incremental_turnover_rub.status === "available").map((scenario) => scenario.scenario_id);
  const actualRangeIds: string[] = [];
  value.scenario_range.rows.forEach((row) => {
    if (!isRecord(row) || !hasExactKeys(row, RANGE_ROW_KEYS) || !isScenarioId(row.scenario_id) ||
      !isFiniteNumber(row.p10) || !isFiniteNumber(row.p50) || !isFiniteNumber(row.p90) ||
      row.p10 > row.p50 || row.p50 > row.p90 || !isEnum(row.quality_status, QUALITY_STATUSES)) failResult();
    const scenario = scenarios.find((item) => item.scenario_id === row.scenario_id);
    if (!scenario || scenario.metrics.incremental_turnover_rub.status !== "available" ||
      !nearlyEqual(row.p10, scenario.metrics.incremental_turnover_rub.p10 as number, 1e-9) ||
      !nearlyEqual(row.p50, scenario.metrics.incremental_turnover_rub.p50 as number, 1e-9) ||
      !nearlyEqual(row.p90, scenario.metrics.incremental_turnover_rub.p90 as number, 1e-9) ||
      row.quality_status !== scenario.quality_status) failResult();
    actualRangeIds.push(row.scenario_id);
  });
  if (actualRangeIds.join("|") !== expectedRangeIds.join("|")) failResult();
  const sourceBudget = scenarios[0].budget.allocated_budget_rub;
  const selected = scenarios.find((scenario) => scenario.scenario_id === value.selected_scenario_id);
  if (!selected || selected.status !== "completed") failResult();
  const selectedMetricIds = [
    "incremental_turnover_rub",
    "incremental_orders",
    "orders_per_100k_rub",
    "avg_basket_delta_rub",
  ] as const;
  selectedMetricIds.forEach((metricId, index) => {
    const headline = headlines[index] as JsonRecord;
    const metric = selected.metrics[metricId];
    if (headline.status !== metric.status || headline.p10 !== metric.p10 || headline.p50 !== metric.p50 ||
      headline.p90 !== metric.p90) failResult();
  });
  const budgetHeadline = headlines[4] as JsonRecord;
  const reliabilityHeadline = headlines[5] as JsonRecord;
  const rankHeadline = headlines[6] as JsonRecord;
  if (budgetHeadline.status !== "available" || budgetHeadline.value !== selected.budget.allocated_budget_rub ||
    reliabilityHeadline.status !== "unavailable" || reliabilityHeadline.value !== null ||
    rankHeadline.value !== selected.safe_rank ||
    rankHeadline.status !== (selected.safe_rank === null ? "unavailable" : "available") ||
    (rankHeadline.value !== null && !isPositiveInteger(rankHeadline.value))) failResult();
  const summaries: Array<[unknown, "channel" | "geo" | "geo_channel"]> = [
    [value.channel_summary, "channel"], [value.geo_summary, "geo"], [value.geo_channel_summary, "geo_channel"],
  ];
  for (const [rows, dimension] of summaries) {
    if (!Array.isArray(rows) || rows.length === 0 || !rows.every((row) => isBudgetComparison(row, dimension))) failResult();
    const keys = rows.map((row) => dimension === "channel" ? row.channel : dimension === "geo" ? row.geo : `${row.geo}\u0000${row.channel}`);
    if (new Set(keys).size !== keys.length) failResult();
    const source = rows.reduce((sum, row) => sum + (row as BudgetComparison).source_budget_rub, 0);
    const selectedTotal = rows.reduce((sum, row) => sum + (row as BudgetComparison).selected_budget_rub, 0);
    if (!nearlyEqual(source, sourceBudget, 1) || !nearlyEqual(selectedTotal, selected.budget.allocated_budget_rub, 1)) failResult();
  }
}

export function parseJobResultView(value: unknown, expectedJobId: string): JobResultViewV1 {
  if (!isRecord(value) || !hasExactKeys(value, RESULT_KEYS) ||
    value.contract_name !== "job_result_view_v1" || value.schema_version !== "1.0.0" ||
    (value.record_origin !== "application_runtime" && value.record_origin !== "sanitized_fixture") ||
    !isOpaqueId(value.job_id) || value.job_id !== expectedJobId || !isOpaqueId(value.result_id) ||
    !isOpaqueId(value.source_overview_id) || !isIsoDateTime(value.updated_at_utc)) failResult();
  if (!isRecord(value.campaign) || !hasExactKeys(value.campaign, CAMPAIGN_KEYS) ||
    !isOpaqueId(value.campaign.campaign_id) || !isText(value.campaign.campaign_name) ||
    !uniqueStrings(value.campaign.segments) || !isIsoDate(value.campaign.start_date) ||
    !isIsoDate(value.campaign.end_date) || value.campaign.start_date > value.campaign.end_date ||
    !isNonNegative(value.campaign.total_budget_rub) || !isPositiveInteger(value.campaign.channels_n) ||
    !isPositiveInteger(value.campaign.geographies_n) || !isFiniteNumber(value.campaign.model_coverage_share) ||
    value.campaign.model_coverage_share < 0 || value.campaign.model_coverage_share > 1) failResult();
  if (!Array.isArray(value.scenarios) || value.scenarios.length !== SCENARIO_IDS.length ||
    !value.scenarios.every((scenario, index) => isScenario(scenario, index))) failResult();
  const scenarios = value.scenarios as unknown as Scenario[];
  for (const rankKey of ["safe_rank", "raw_rank"] as const) {
    const ranks = scenarios.map((scenario) => scenario[rankKey]).filter((rank): rank is number => rank !== null);
    if (new Set(ranks).size !== ranks.length) failResult();
  }
  if (!isRecord(value.recommendation) || !hasExactKeys(value.recommendation, RECOMMENDATION_KEYS) ||
    !isEnum(value.recommendation.status, ["recommended", "no_safe_recommendation", "unavailable"] as const) ||
    !isText(value.recommendation.title) || !isText(value.recommendation.display_text) ||
    !isText(value.recommendation.decision_scope_text) || !isNullablePositiveInteger(value.recommendation.safe_rank) ||
    !isNullablePositiveInteger(value.recommendation.raw_rank) || !isRecord(value.recommendation.best_safe) ||
    !hasExactKeys(value.recommendation.best_safe, BEST_SAFE_KEYS) ||
    typeof value.recommendation.best_safe.available !== "boolean" || !isNullablePositiveInteger(value.recommendation.best_safe.safe_rank) ||
    !isNullablePositiveInteger(value.recommendation.best_safe.raw_rank) || !isText(value.recommendation.best_safe.display_text)) failResult();
  const recommendation = value.recommendation as JsonRecord;
  const bestSafe = recommendation.best_safe as JsonRecord;
  const recommendedRows = scenarios.filter((scenario) => scenario.is_recommended);
  if (recommendation.status === "recommended") {
    if (!isScenarioId(recommendation.scenario_id) || recommendedRows.length !== 1 ||
      recommendedRows[0].scenario_id !== recommendation.scenario_id || recommendedRows[0].status !== "completed" ||
      recommendation.safe_rank !== recommendedRows[0].safe_rank || recommendation.raw_rank !== recommendedRows[0].raw_rank) failResult();
  } else if (recommendation.scenario_id !== null || recommendation.safe_rank !== null ||
    recommendation.raw_rank !== null || recommendedRows.length !== 0) failResult();
  const bestSafeRows = scenarios.filter((scenario) => scenario.is_best_safe);
  if (bestSafe.available) {
    const row = scenarios.find((scenario) => scenario.scenario_id === bestSafe.scenario_id);
    if (!row || row.status !== "completed" || bestSafeRows.length !== 1 || bestSafeRows[0] !== row ||
      bestSafe.safe_rank !== row.safe_rank || bestSafe.raw_rank !== row.raw_rank) failResult();
  } else if (bestSafe.scenario_id !== null || bestSafe.safe_rank !== null ||
    bestSafe.raw_rank !== null || bestSafeRows.length !== 0) failResult();
  if (recommendation.status !== "recommended" && bestSafe.available) failResult();
  if (recommendation.status === "recommended" && recommendation.scenario_id === "S06" && !bestSafe.available) failResult();
  if (!isRecord(value.overview)) failResult();
  const overview = value.overview as JsonRecord;
  validateResultOverview(overview, scenarios);
  const expectedSelected = recommendation.status === "recommended" ? recommendation.scenario_id : "S01";
  if (overview.selected_scenario_id !== expectedSelected) failResult();
  if (!isReliability(value.reliability)) failResult();
  const selectedScenario = scenarios.find((scenario) => scenario.scenario_id === overview.selected_scenario_id);
  if (!selectedScenario || JSON.stringify(value.reliability) !== JSON.stringify(selectedScenario.reliability)) failResult();
  if (!Array.isArray(value.warnings)) failResult();
  const warningCodes = new Set<string>();
  for (const warning of value.warnings) {
    if (!isRecord(warning) || !hasExactKeys(warning, WARNING_KEYS) || typeof warning.code !== "string" ||
      !WARNING_CODE_RE.test(warning.code) || warningCodes.has(warning.code) ||
      !isEnum(warning.severity, ["info", "caution", "manual_review", "blocking"] as const) ||
      !isText(warning.title) || !isText(warning.display_text) || !isText(warning.recommended_action) ||
      !isEnum(warning.scope, ["campaign", "selected_scenario", "recommendation", "scenario6"] as const)) failResult();
    warningCodes.add(warning.code);
  }
  if (!isRecord(value.best_raw) || !hasExactKeys(value.best_raw, BEST_RAW_KEYS) ||
    typeof value.best_raw.available !== "boolean" || !isNullablePositiveInteger(value.best_raw.raw_rank) ||
    !isNullablePositiveInteger(value.best_raw.safe_rank) ||
    !isEnum(value.best_raw.blocking_cells_status, ["available", "unavailable", "not_applicable"] as const) ||
    !Array.isArray(value.best_raw.blocking_cells)) failResult();
  if (value.best_raw.available) {
    if (value.best_raw.scenario_id !== "S06" || !isText(value.best_raw.reason_not_recommended) ||
      !isRecord(value.best_raw.metrics) || !hasExactKeys(value.best_raw.metrics, AUDIT_METRIC_KEYS) ||
      !isQuantileMetric(value.best_raw.metrics.incremental_turnover_rub, "RUB", "audit_only", null) ||
      !isQuantileMetric(value.best_raw.metrics.roas, "ratio", "audit_only", null)) failResult();
    if ((value.best_raw.blocking_cells_status === "available") !== (value.best_raw.blocking_cells.length > 0) ||
      value.best_raw.blocking_cells_status === "not_applicable") failResult();
  } else if (value.best_raw.scenario_id !== null || value.best_raw.raw_rank !== null || value.best_raw.safe_rank !== null ||
    value.best_raw.reason_not_recommended !== null || value.best_raw.metrics !== null || value.best_raw.blocking_cells.length !== 0 ||
    value.best_raw.blocking_cells_status === "available") failResult();
  if (!value.best_raw.blocking_cells.every((cell) => isRecord(cell) && hasExactKeys(cell, BLOCKING_CELL_KEYS) &&
    isText(cell.segment) && isText(cell.geo) && isText(cell.channel) && isText(cell.reason))) failResult();
  const bestRawRows = scenarios.filter((scenario) => scenario.is_best_raw);
  if (bestRawRows.length > 1 || (bestRawRows[0] && bestRawRows[0].scenario_id !== "S06")) failResult();
  if (value.best_raw.available && bestRawRows.length === 1) {
    if (bestRawRows[0].raw_rank !== value.best_raw.raw_rank ||
      bestRawRows[0].safe_rank !== value.best_raw.safe_rank) failResult();
  }
  if (!value.best_raw.available && bestRawRows.length === 1) {
    if (recommendation.status !== "recommended" || recommendation.scenario_id !== "S06" ||
      bestRawRows[0].status !== "completed" || !bestRawRows[0].is_recommended) failResult();
  }
  if (!isRecord(value.media_plan) || !hasExactKeys(value.media_plan, MEDIA_SUMMARY_KEYS) ||
    value.media_plan.endpoint !== `/api/v1/jobs/${expectedJobId}/media-plan` ||
    value.media_plan.selected_scenario_id !== value.overview.selected_scenario_id || value.media_plan.grain !== "geo_channel_total" ||
    !Array.isArray(value.media_plan.scenario_options) || value.media_plan.scenario_options.length !== SCENARIO_IDS.length) failResult();
  value.media_plan.scenario_options.forEach((option, index) => {
    if (!isRecord(option) || !hasExactKeys(option, SCENARIO_OPTION_KEYS) || option.scenario_id !== SCENARIO_IDS[index] ||
      !isText(option.title) || !isEnum(option.status, RESULT_STATUSES) || option.title !== scenarios[index].title ||
      option.status !== scenarios[index].status) failResult();
  });
  if (!isRecord(value.media_plan.daily_plan) || !hasExactKeys(value.media_plan.daily_plan, UNAVAILABLE_TEXT_KEYS) ||
    value.media_plan.daily_plan.status !== "unavailable" || !isText(value.media_plan.daily_plan.display_text) ||
    !isRecord(value.media_plan.map) || !hasExactKeys(value.media_plan.map, MAP_KEYS) || value.media_plan.map.status !== "unavailable" ||
    !isText(value.media_plan.map.display_text) || value.media_plan.map.geo_points !== null ||
    value.media_plan.map.coordinate_catalog_version !== null || !isArtifactAvailability(value.media_plan.working_media_plan)) failResult();
  if (!isRecord(value.report) || !hasExactKeys(value.report, REPORT_KEYS) ||
    !isEnum(value.report.status, ["ready", "failed", "unavailable"] as const) || !isText(value.report.display_text) ||
    (value.report.generated_at_utc !== null && !isIsoDateTime(value.report.generated_at_utc)) ||
    !Array.isArray(value.report.sheets) || !isArtifactAvailability(value.report.working_media_plan)) failResult();
  if (value.report.status === "ready") {
    if (!isArtifact(value.report.artifact) ||
      value.report.artifact.media_type !== "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" ||
      value.report.sheets.length === 0) failResult();
  } else if (value.report.artifact !== null || value.report.sheets.length !== 0 || value.report.generated_at_utc !== null) failResult();
  const sheetNames = new Set<string>();
  for (const sheet of value.report.sheets) {
    if (!isRecord(sheet) || !hasExactKeys(sheet, SHEET_KEYS) || !isText(sheet.sheet_name) ||
      sheetNames.has(sheet.sheet_name) || !isText(sheet.title) ||
      (sheet.description !== null && !isText(sheet.description))) failResult();
    sheetNames.add(sheet.sheet_name);
  }
  if (JSON.stringify(value.media_plan.working_media_plan) !== JSON.stringify(value.report.working_media_plan)) failResult();
  if (!Array.isArray(value.limitations) || value.limitations.length === 0) failResult();
  const limitationCodes = new Set<string>();
  for (const limitation of value.limitations) {
    if (!isRecord(limitation) || !hasExactKeys(limitation, LIMITATION_KEYS) || !isText(limitation.code) ||
      limitationCodes.has(limitation.code) || !isText(limitation.display_text)) failResult();
    limitationCodes.add(limitation.code);
  }
  if (hasForbiddenPath(value)) failResult();
  return value as unknown as JobResultViewV1;
}

export function normalizeScenarioMediaPlanQuery(query: ScenarioMediaPlanQuery): NormalizedScenarioMediaPlanQuery {
  const page = query.page ?? 1;
  const pageSize = query.pageSize ?? 100;
  const channel = query.channel ?? null;
  const geo = query.geo ?? null;
  if (!isScenarioId(query.scenarioId) || !isPositiveInteger(page) || !isPositiveInteger(pageSize) || pageSize > 500 ||
    (channel !== null && !isText(channel)) || (geo !== null && !isText(geo))) {
    throw new MediaPlanQueryUnsupportedError();
  }
  return { scenarioId: query.scenarioId, page, pageSize, channel, geo };
}

function isPlanBudgetRow(value: unknown, dimensions: readonly ("channel" | "geo")[]): value is JsonRecord {
  const keys = dimensions.length === 1 ? (dimensions[0] === "channel" ? CHANNEL_BUDGET_KEYS : GEO_BUDGET_KEYS) : GEO_CHANNEL_BUDGET_KEYS;
  if (!isRecord(value) || !hasExactKeys(value, keys) ||
    (dimensions.includes("channel") && !isText(value.channel)) ||
    (dimensions.includes("geo") && !isText(value.geo)) ||
    !isNonNegative(value.source_budget_rub) || !isNonNegative(value.selected_budget_rub) ||
    !isFiniteNumber(value.delta_rub) || !isEnum(value.quality_status, QUALITY_STATUSES) || !isText(value.quality_display_text)) return false;
  const delta = value.selected_budget_rub - value.source_budget_rub;
  return nearlyEqual(value.delta_rub, delta) &&
    (value.source_budget_rub === 0 ? value.delta_pct === null : isFiniteNumber(value.delta_pct) && nearlyEqual(value.delta_pct, delta / value.source_budget_rub * 100, 1e-6));
}

export function parseScenarioMediaPlan(
  value: unknown,
  expectedJobId: string,
  resultView: JobResultViewV1,
  query: ScenarioMediaPlanQuery,
): ScenarioMediaPlanV1 {
  const normalized = normalizeScenarioMediaPlanQuery(query);
  try {
    parseJobResultView(resultView, expectedJobId);
  } catch {
    failPlan();
  }
  if (!isRecord(value) || !hasExactKeys(value, PLAN_KEYS) || value.contract_name !== "scenario_media_plan_v1" ||
    value.schema_version !== "1.0.0" || value.record_origin !== resultView.record_origin ||
    !isOpaqueId(value.job_id) || value.job_id !== expectedJobId || value.job_id !== resultView.job_id ||
    value.result_id !== resultView.result_id || value.campaign_id !== resultView.campaign.campaign_id ||
    value.grain !== "geo_channel_total" || !isIsoDateTime(value.updated_at_utc) ||
    value.updated_at_utc !== resultView.updated_at_utc) failPlan();
  if (!isRecord(value.scenario) || !hasExactKeys(value.scenario, PLAN_SCENARIO_KEYS) ||
    value.scenario.scenario_id !== normalized.scenarioId || value.scenario.status !== "completed" ||
    typeof value.scenario.is_selected !== "boolean" || !isNullablePositiveInteger(value.scenario.safe_rank) ||
    !isNullablePositiveInteger(value.scenario.raw_rank) || !isEnum(value.scenario.quality_status, QUALITY_STATUSES) ||
    !isText(value.scenario.title) || !isText(value.scenario.quality_display_text)) failPlan();
  const resultScenario = resultView.scenarios.find((scenario) => scenario.scenario_id === normalized.scenarioId);
  if (!resultScenario || resultScenario.status !== "completed" || value.scenario.title !== resultScenario.title ||
    value.scenario.safe_rank !== resultScenario.safe_rank ||
    value.scenario.raw_rank !== resultScenario.raw_rank || value.scenario.quality_status !== resultScenario.quality_status ||
    value.scenario.quality_display_text !== resultScenario.quality_display_text) failPlan();
  if (!isRecord(value.source_artifact) || !hasExactKeys(value.source_artifact, SOURCE_ARTIFACT_KEYS) ||
    !isOpaqueId(value.source_artifact.artifact_id) || value.source_artifact.kind !== "recommended_allocations_csv" ||
    typeof value.source_artifact.sha256 !== "string" || !SHA256_RE.test(value.source_artifact.sha256)) failPlan();
  if (!isRecord(value.filters) || !hasExactKeys(value.filters, FILTER_KEYS) || value.filters.channel !== normalized.channel ||
    value.filters.geo !== normalized.geo || value.filters.date !== null) failPlan();
  if (!isRecord(value.pagination) || !hasExactKeys(value.pagination, PAGINATION_KEYS) ||
    value.pagination.page !== normalized.page || value.pagination.page_size !== normalized.pageSize ||
    !isNonNegativeInteger(value.pagination.total_rows) || !isNonNegativeInteger(value.pagination.total_pages)) failPlan();
  const expectedPages = value.pagination.total_rows === 0 ? 0 : Math.ceil(value.pagination.total_rows / normalized.pageSize);
  if (value.pagination.total_pages !== expectedPages) failPlan();
  if (!isRecord(value.totals) || !hasExactKeys(value.totals, TOTAL_KEYS) || value.totals.reconciliation_status !== "reconciled" ||
    !isNonNegative(value.totals.requested_budget_rub) || !isNonNegative(value.totals.source_budget_rub) ||
    !isNonNegative(value.totals.selected_budget_rub) || !isNonNegative(value.totals.unallocated_budget_rub) ||
    !isFiniteNumber(value.totals.delta_rub) ||
    !nearlyEqual(value.totals.selected_budget_rub - value.totals.source_budget_rub, value.totals.delta_rub, 1) ||
    !nearlyEqual(value.totals.selected_budget_rub + value.totals.unallocated_budget_rub, value.totals.requested_budget_rub, 1) ||
    !nearlyEqual(value.totals.requested_budget_rub, resultScenario.budget.requested_budget_rub, 1) ||
    !nearlyEqual(value.totals.selected_budget_rub, resultScenario.budget.allocated_budget_rub, 1) ||
    !nearlyEqual(value.totals.unallocated_budget_rub, resultScenario.budget.unallocated_budget_rub, 1) ||
    !nearlyEqual(value.totals.source_budget_rub, resultView.scenarios[0].budget.allocated_budget_rub, 1)) failPlan();
  if (!isRecord(value.filtered_totals) || !hasExactKeys(value.filtered_totals, FILTERED_TOTAL_KEYS) ||
    !isNonNegative(value.filtered_totals.source_budget_rub) || !isNonNegative(value.filtered_totals.selected_budget_rub) ||
    !isFiniteNumber(value.filtered_totals.delta_rub) ||
    !nearlyEqual(value.filtered_totals.selected_budget_rub - value.filtered_totals.source_budget_rub, value.filtered_totals.delta_rub, 1) ||
    value.filtered_totals.source_budget_rub > value.totals.source_budget_rub + 1 ||
    value.filtered_totals.selected_budget_rub > value.totals.selected_budget_rub + 1) failPlan();
  if (!Array.isArray(value.rows)) failPlan();
  const expectedRows = Math.min(normalized.pageSize, Math.max(value.pagination.total_rows - (normalized.page - 1) * normalized.pageSize, 0));
  if (value.rows.length !== expectedRows) failPlan();
  const rowSortKeys: string[] = [];
  for (const row of value.rows) {
    if (!isRecord(row) || !hasExactKeys(row, PLAN_ROW_KEYS) || row.scenario_id !== normalized.scenarioId ||
      row.campaign_id !== resultView.campaign.campaign_id || !isText(row.segment) || !isText(row.geo) || !isText(row.channel) ||
      row.date !== null || !isNonNegative(row.source_budget_rub) || !isNonNegative(row.selected_budget_rub) ||
      !isFiniteNumber(row.delta_rub) || !isFiniteNumber(row.source_budget_share) || row.source_budget_share < 0 || row.source_budget_share > 1 ||
      !isFiniteNumber(row.selected_budget_share) || row.selected_budget_share < 0 || row.selected_budget_share > 1 ||
      !isEnum(row.quality_status, QUALITY_STATUSES) || !isText(row.quality_display_text)) failPlan();
    const delta = row.selected_budget_rub - row.source_budget_rub;
    if (!nearlyEqual(row.delta_rub, delta) || (row.source_budget_rub === 0 ? row.delta_pct !== null :
      !isFiniteNumber(row.delta_pct) || !nearlyEqual(row.delta_pct, delta / row.source_budget_rub * 100, 1e-6)) ||
      !nearlyEqual(row.source_budget_share, value.totals.source_budget_rub === 0 ? 0 : row.source_budget_rub / value.totals.source_budget_rub, 1e-9) ||
      !nearlyEqual(row.selected_budget_share, value.totals.selected_budget_rub === 0 ? 0 : row.selected_budget_rub / value.totals.selected_budget_rub, 1e-9)) failPlan();
    rowSortKeys.push(`${row.segment}\u0000${row.geo}\u0000${row.channel}`);
  }
  if (new Set(rowSortKeys).size !== rowSortKeys.length || rowSortKeys.some((key, index) => index > 0 && key < rowSortKeys[index - 1])) failPlan();
  if (value.pagination.total_rows === 0 && (value.filtered_totals.source_budget_rub !== 0 || value.filtered_totals.selected_budget_rub !== 0 || value.filtered_totals.delta_rub !== 0)) failPlan();
  if (value.pagination.total_rows <= normalized.pageSize && normalized.page === 1) {
    const rowSource = value.rows.reduce((sum, row) => sum + (row as JsonRecord).source_budget_rub as number, 0);
    const rowSelected = value.rows.reduce((sum, row) => sum + (row as JsonRecord).selected_budget_rub as number, 0);
    if (!nearlyEqual(rowSource, value.filtered_totals.source_budget_rub, 1) || !nearlyEqual(rowSelected, value.filtered_totals.selected_budget_rub, 1)) failPlan();
  }
  if (!isRecord(value.aggregates) || !hasExactKeys(value.aggregates, AGGREGATE_KEYS)) failPlan();
  const aggregateDefinitions: Array<[unknown, readonly ("channel" | "geo")[]]> = [
    [value.aggregates.by_channel, ["channel"]], [value.aggregates.by_geo, ["geo"]], [value.aggregates.by_geo_channel, ["geo", "channel"]],
  ];
  for (const [rows, dimensions] of aggregateDefinitions) {
    if (!Array.isArray(rows) || rows.length === 0 || !rows.every((row) => isPlanBudgetRow(row, dimensions))) failPlan();
    const keys = rows.map((row) => dimensions.map((dimension) => (row as JsonRecord)[dimension]).join("\u0000"));
    if (new Set(keys).size !== keys.length) failPlan();
    const source = rows.reduce((sum, row) => sum + ((row as JsonRecord).source_budget_rub as number), 0);
    const selected = rows.reduce((sum, row) => sum + ((row as JsonRecord).selected_budget_rub as number), 0);
    if (!nearlyEqual(source, value.totals.source_budget_rub, 1) || !nearlyEqual(selected, value.totals.selected_budget_rub, 1)) failPlan();
  }
  for (const unavailable of [value.aggregates.by_date, value.aggregates.channel_date_matrix]) {
    if (!isRecord(unavailable) || !hasExactKeys(unavailable, UNAVAILABLE_ROWS_KEYS) || unavailable.status !== "unavailable" ||
      !isText(unavailable.display_text) || unavailable.rows !== null) failPlan();
  }
  if (!isRecord(value.aggregates.geo_channel_matrix) || !hasExactKeys(value.aggregates.geo_channel_matrix, READY_MATRIX_KEYS) ||
    value.aggregates.geo_channel_matrix.status !== "ready" || !isText(value.aggregates.geo_channel_matrix.display_text) ||
    JSON.stringify(value.aggregates.geo_channel_matrix.rows) !== JSON.stringify(value.aggregates.by_geo_channel)) failPlan();
  if (!isRecord(value.map) || !hasExactKeys(value.map, MAP_KEYS) || value.map.status !== "unavailable" || !isText(value.map.display_text) ||
    value.map.geo_points !== null || value.map.coordinate_catalog_version !== null || !isRecord(value.working_media_plan) ||
    !hasExactKeys(value.working_media_plan, PLAN_ARTIFACT_AVAILABILITY_KEYS) || value.working_media_plan.status !== "unavailable" ||
    !isText(value.working_media_plan.display_text) || value.working_media_plan.artifact !== null) failPlan();
  if (!Array.isArray(value.limitations) || value.limitations.length === 0 || !value.limitations.every((limitation) =>
    isRecord(limitation) && hasExactKeys(limitation, LIMITATION_KEYS) && isText(limitation.code) && isText(limitation.display_text))) failPlan();
  if (new Set(value.limitations.map((limitation) => (limitation as JsonRecord).code)).size !== value.limitations.length || hasForbiddenPath(value)) failPlan();
  return value as unknown as ScenarioMediaPlanV1;
}

function apiEndpoint(path: string, baseUrl: string): string {
  return `${baseUrl.replace(/\/+$/, "")}${path}`;
}

function resultViewPath(jobId: string): string {
  return `/api/v1/jobs/${encodeURIComponent(jobId)}/result-view`;
}

function mediaPlanPath(jobId: string, query: NormalizedScenarioMediaPlanQuery): string {
  const parameters = new URLSearchParams({
    scenario_id: query.scenarioId,
    page: String(query.page),
    page_size: String(query.pageSize),
  });
  if (query.channel !== null) parameters.set("channel", query.channel);
  if (query.geo !== null) parameters.set("geo", query.geo);
  return `/api/v1/jobs/${encodeURIComponent(jobId)}/media-plan?${parameters.toString()}`;
}

async function responseJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

export async function getJobResultView(
  jobId: string,
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<JobResultViewV1> {
  let response: Response;
  try {
    response = await fetch(apiEndpoint(resultViewPath(jobId), baseUrl), { headers: { Accept: "application/json" }, signal });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new JobResultRequestError();
  }
  if (response.status === 404) {
    const payload = await responseJson(response);
    const code = productErrorCode(payload);
    if (code === "JOB_NOT_FOUND") throw new JobResultNotFoundError();
    if (code === "RESOURCE_NOT_READY") throw new JobResultNotReadyError();
    if (code === null) throw new UnsupportedJobResultContractError(response.status);
    throw new JobResultRequestError(response.status);
  }
  if (response.status === 409) throw new JobResultInconsistentError();
  if (response.status === 503) throw new JobResultUnavailableError();
  if (!response.ok) throw new JobResultRequestError(response.status);
  const payload = await responseJson(response);
  if (payload === undefined) throw new UnsupportedJobResultContractError(response.status);
  try {
    return parseJobResultView(payload, jobId);
  } catch (error) {
    if (error instanceof UnsupportedJobResultContractError) throw new UnsupportedJobResultContractError(response.status);
    throw error;
  }
}

export async function getScenarioMediaPlan(
  jobId: string,
  query: ScenarioMediaPlanQuery,
  resultView: JobResultViewV1,
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<ScenarioMediaPlanV1> {
  const normalized = normalizeScenarioMediaPlanQuery(query);
  let response: Response;
  try {
    response = await fetch(apiEndpoint(mediaPlanPath(jobId, normalized), baseUrl), { headers: { Accept: "application/json" }, signal });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new MediaPlanRequestError();
  }
  if (response.status === 404) {
    const payload = await responseJson(response);
    const code = productErrorCode(payload);
    if (code === "JOB_NOT_FOUND") throw new JobResultNotFoundError();
    if (code === "RESOURCE_NOT_READY") throw new JobResultNotReadyError();
    if (code === null) throw new UnsupportedScenarioMediaPlanContractError(response.status);
    throw new MediaPlanRequestError(response.status);
  }
  if (response.status === 409) throw new JobResultInconsistentError();
  if (response.status === 422) throw new MediaPlanQueryUnsupportedError();
  if (response.status === 503) throw new MediaPlanUnavailableError();
  if (!response.ok) throw new MediaPlanRequestError(response.status);
  const payload = await responseJson(response);
  if (payload === undefined) throw new UnsupportedScenarioMediaPlanContractError(response.status);
  try {
    return parseScenarioMediaPlan(payload, jobId, resultView, normalized);
  } catch (error) {
    if (error instanceof UnsupportedScenarioMediaPlanContractError) {
      throw new UnsupportedScenarioMediaPlanContractError(response.status);
    }
    throw error;
  }
}

export function resolveArtifactDownloadUrl(
  downloadPath: string,
  baseUrl = appEnv.apiBaseUrl,
): string {
  if (!DOWNLOAD_PATH_RE.test(downloadPath)) throw new UnsupportedJobResultContractError();
  if (baseUrl === "") return downloadPath;
  let parsedBase: URL;
  try {
    parsedBase = new URL(baseUrl);
  } catch {
    throw new UnsupportedJobResultContractError();
  }
  if ((parsedBase.protocol !== "http:" && parsedBase.protocol !== "https:") || parsedBase.username || parsedBase.password ||
    parsedBase.search || parsedBase.hash) throw new UnsupportedJobResultContractError();
  const resolved = apiEndpoint(downloadPath, baseUrl);
  let parsedResolved: URL;
  try {
    parsedResolved = new URL(resolved);
  } catch {
    throw new UnsupportedJobResultContractError();
  }
  if (parsedResolved.origin !== parsedBase.origin || parsedResolved.search || parsedResolved.hash) {
    throw new UnsupportedJobResultContractError();
  }
  return resolved;
}
