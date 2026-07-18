import type { GeoCatalogV1 } from "./generated/geo-catalog-v1";
import type { JobResultViewV2 } from "./generated/job-result-view-v2";
import type { ModelOverviewV2 } from "./generated/model-overview-v2";
import type { ModelPassportV2 } from "./generated/model-passport-v2";
import type { ScenarioId, ScenarioMediaPlanV2 } from "./generated/scenario-media-plan-v2";
import type { ValidationResultV2 } from "./generated/validation-result-v2";
import type { WorkspaceGeoBudgetV1 } from "./generated/workspace-geo-budget-v1";
import { appEnv } from "../config/env";
import { credentialedFetch } from "./credentialed-fetch";

type JsonRecord = Record<string, unknown>;

const SCENARIOS = ["S01", "S02", "S03", "S04", "S05", "S06"] as const;
const GEO_ID = /^geo_[0-9a-f]{16}$/;
const OPAQUE_ID = /^[a-z][a-z0-9_]*_[0-9a-f]{12,64}$/;
const PACKAGE_ID = /^pkg_[0-9a-f]{16}_[0-9a-f]{16}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const ABSOLUTE_PATH = /^(?:\/|[A-Za-z]:[\\/]|file:\/\/)/i;
const TRUNCATED_GEOS = /\.\.\.\s*ещ[её]\s+\d+/i;
const INTERNAL_S5_VARIANT = /\bS5\.[12]\b/i;
const FORBIDDEN_PRESENTATION = /(?:\borders?\b|заказ(?:ы|ов|ами|ах)?|avg[ _-]?basket|average[ _-]?basket|средн(?:ий|его|ему)?\s+чек|част[ьи]\s+дополнительного\s+оборота|Digital_Performance|OOH_Total)/i;
const MONEY_TOLERANCE_RUB = 1;
const SHARE_TOLERANCE = 1e-8;
const CHANNEL_DISPLAY_NAMES: Readonly<Record<string, string>> = {
  Digital_Performance: "Цифровая реклама",
  OOH_Total: "Наружная реклама",
  "Нац_ТВ": "Национальное ТВ",
  "Рег_ТВ": "Региональное ТВ",
  "Радио": "Радио",
  Indoor: "Indoor",
};
const RESULT_KEYS = ["contract_name", "schema_version", "record_origin", "job_id", "result_id", "source_overview_id", "updated_at_utc", "campaign", "recommendation", "scenarios", "media_plan", "map", "limitations"] as const;
const RESULT_CAMPAIGN_KEYS = ["campaign_id", "campaign_name", "segments", "start_date", "end_date", "requested_budget_rub", "channels", "geographies_n", "geographies"] as const;
const RESULT_RECOMMENDATION_KEYS = ["decision_status", "review_status", "scenario_id", "title", "display_text", "decision_scope_text"] as const;
const RESULT_SCENARIO_KEYS = ["scenario_id", "name", "description", "scenario_kind", "scenario_variant", "status", "is_recommended", "decision_status", "review_status", "budget", "incremental_turnover", "roas", "risk_budget", "reliability", "limiting_constraints"] as const;
const BUDGET_KEYS = ["requested_budget_rub", "allocated_budget_rub", "unallocated_budget_rub", "allocation_share"] as const;
const QUANTILE_KEYS = ["status", "unit", "p10", "p50", "p90", "display_text"] as const;
const ROAS_KEYS = ["allocated_budget", "requested_budget", "primary_denominator_kind", "primary_denominator_budget_rub"] as const;
const RISK_KEYS = ["within_support_budget_rub", "within_support_share", "controlled_extrapolation_budget_rub", "controlled_extrapolation_share", "high_risk_budget_rub", "high_risk_share", "within_support_cells_n", "controlled_extrapolation_cells_n", "high_risk_cells_n"] as const;
const RELIABILITY_KEYS = ["status", "display_text", "evidence_codes", "safe_rank", "raw_rank"] as const;
const PLAN_KEYS = ["contract_name", "schema_version", "record_origin", "job_id", "result_id", "campaign_id", "scenario", "source_artifact", "grain", "filters", "pagination", "totals", "filtered_totals", "rows", "aggregates", "map", "working_media_plan", "limitations", "updated_at_utc"] as const;
const VALIDATION_KEYS = ["contract_name", "schema_version", "validation_id", "status", "job_creation_allowed", "file_validation", "model_limitations", "map_coverage", "geo_points"] as const;
const PASSPORT_KEYS = ["contract_name", "schema_version", "record_origin", "serving", "package", "data", "coverage", "validation", "channel_policies", "caveats"] as const;
const OVERVIEW_KEYS = ["contract_name", "schema_version", "serving", "summary", "channel_policies", "limitations"] as const;
const CATALOG_KEYS = ["contract_name", "schema_version", "catalog_version", "coordinates_source", "coordinates_source_version_or_date", "coordinates_license", "status", "display_text", "geographies_n", "coverage", "entries"] as const;
const WORKSPACE_KEYS = ["contract_name", "schema_version", "catalog_version", "status", "display_text", "total_budget_rub", "campaigns_n", "geographies_n", "coverage", "rows"] as const;
const ERROR_KEYS = ["error"] as const;
const ERROR_DETAIL_KEYS = ["code", "display_text", "retryable", "user_action"] as const;

export interface ScenarioMediaPlanV2Query {
  scenarioId: ScenarioId;
  page?: number;
  pageSize?: number;
  channel?: string | null;
  geo?: string | null;
}

export class BusinessSemanticsNotFoundError extends Error {
  readonly status = 404;
  constructor() { super("Запрошенные данные не найдены."); this.name = "BusinessSemanticsNotFoundError"; }
}
export class BusinessSemanticsNotReadyError extends Error {
  readonly status = 404;
  readonly retryable = true;
  constructor() { super("Данные еще не готовы."); this.name = "BusinessSemanticsNotReadyError"; }
}
export class BusinessSemanticsUnavailableError extends Error {
  readonly status = 503;
  readonly retryable = true;
  constructor() { super("Данные временно недоступны."); this.name = "BusinessSemanticsUnavailableError"; }
}
export class BusinessSemanticsQueryError extends Error {
  readonly status = 422;
  constructor() { super("Параметры запроса не поддерживаются."); this.name = "BusinessSemanticsQueryError"; }
}
export class BusinessSemanticsRequestError extends Error {
  readonly retryable: boolean;
  constructor(readonly status: number | null = null) { super("Не удалось получить данные."); this.name = "BusinessSemanticsRequestError"; this.retryable = status === null || status >= 500; }
}
/** A malformed result is deliberately indistinguishable from an unsupported v2 response. */
export class UnsupportedBusinessSemanticsContractError extends Error {
  constructor(readonly status: number | null = null) { super("Данные результата имеют неподдерживаемый формат."); this.name = "UnsupportedBusinessSemanticsContractError"; }
}

function record(value: unknown): value is JsonRecord { return value !== null && typeof value === "object" && !Array.isArray(value); }
function exact(value: JsonRecord, keys: readonly string[]): boolean { const actual = Object.keys(value); return actual.length === keys.length && keys.every((key) => key in value); }
function text(value: unknown): value is string { return typeof value === "string" && value.trim().length > 0; }
function number(value: unknown): value is number { return typeof value === "number" && Number.isFinite(value); }
function nonNegative(value: unknown): value is number { return number(value) && value >= 0; }
function integer(value: unknown): value is number { return number(value) && Number.isInteger(value); }
function nonNegativeInteger(value: unknown): value is number { return integer(value) && value >= 0; }
function positiveIntegerOrNull(value: unknown): boolean { return value === null || (integer(value) && value >= 1); }
function enumValue<T extends readonly string[]>(value: unknown, values: T): value is T[number] { return typeof value === "string" && values.includes(value as T[number]); }
function isoDate(value: unknown): value is string { if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false; const [year, month, day] = value.split("-").map(Number); const date = new Date(Date.UTC(year, month - 1, day)); return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day; }
function isoDateTime(value: unknown): value is string { return typeof value === "string" && Number.isFinite(Date.parse(value)) && /^\d{4}-\d{2}-\d{2}T/.test(value); }
function moneyNear(left: number, right: number): boolean { return Math.abs(left - right) <= MONEY_TOLERANCE_RUB; }
function shareNear(left: number, right: number): boolean { return Math.abs(left - right) <= SHARE_TOLERANCE; }
function uniqueStrings(value: unknown, nonempty = true): value is string[] { return Array.isArray(value) && value.every((item) => typeof item === "string" && (!nonempty || item.trim().length > 0)) && new Set(value).size === value.length; }
function uniqueBy<T>(values: readonly T[], key: (value: T) => string): boolean { return new Set(values.map(key)).size === values.length; }

function hasUnsafeString(value: unknown, key = ""): boolean {
  if (typeof value === "string") return TRUNCATED_GEOS.test(value) || INTERNAL_S5_VARIANT.test(value) || (ABSOLUTE_PATH.test(value) && !(key === "endpoint" && /^\/api\/v1\/jobs\/[a-z][a-z0-9_]*_[0-9a-f]{12,64}\/media-plan-v2$/u.test(value))) || (/(display_text|title|name|description|what|why|recommended_action|decision_scope_text|limiting_constraints)$/u.test(key) && FORBIDDEN_PRESENTATION.test(value));
  if (Array.isArray(value)) return value.some((item) => hasUnsafeString(item, key));
  return record(value) && Object.entries(value).some(([childKey, item]) => hasUnsafeString(item, childKey));
}
function channel(value: unknown): boolean {
  if (!record(value) || !exact(value, ["channel_id", "channel_display_name"]) || typeof value.channel_id !== "string") return false;
  return CHANNEL_DISPLAY_NAMES[value.channel_id] === value.channel_display_name;
}
function geo(value: unknown, regions = false): boolean {
  const keys = regions ? ["geo_id", "geo_display_name", "latitude", "longitude", "coordinates_status", "region_id", "region_display_name"] : ["geo_id", "geo_display_name"];
  if (!record(value) || !exact(value, keys) || typeof value.geo_id !== "string" || !GEO_ID.test(value.geo_id) || !text(value.geo_display_name) || TRUNCATED_GEOS.test(value.geo_display_name)) return false;
  if (!regions) return true;
  if (!coordinates(value)) return false;
  return value.coordinates_status === "canonical"
    ? text(value.region_id) && text(value.region_display_name)
    : value.region_id === null && value.region_display_name === null;
}
function coordinates(value: JsonRecord): boolean {
  if (!enumValue(value.coordinates_status, ["canonical", "unavailable"] as const)) return false;
  if (value.coordinates_status === "unavailable") return value.latitude === null && value.longitude === null;
  return number(value.latitude) && value.latitude >= -90 && value.latitude <= 90 && number(value.longitude) && value.longitude >= -180 && value.longitude <= 180;
}
function mapCoverage(value: unknown, rows: JsonRecord[], budgetKey?: "budget_rub" | "total_budget_rub"): boolean {
  if (!record(value) || !exact(value, budgetKey
    ? ["status", "located_geographies_n", "unlocated_geographies_n", "unlocated_geographies", "located_budget_rub", "unlocated_budget_rub", "unlocated_budget_share"]
    : ["status", "located_geographies_n", "unlocated_geographies_n", "unlocated_geographies"])) return false;
  const located = rows.filter((row) => row.coordinates_status === "canonical");
  const unlocated = rows.filter((row) => row.coordinates_status === "unavailable");
  const expectedStatus = rows.length > 0 && located.length === rows.length ? "available" : located.length > 0 ? "partial" : "unavailable";
  if (value.status !== expectedStatus || value.located_geographies_n !== located.length || value.unlocated_geographies_n !== unlocated.length || !Array.isArray(value.unlocated_geographies) || !value.unlocated_geographies.every((item) => geo(item)) || !uniqueBy(value.unlocated_geographies, (item) => (item as JsonRecord).geo_id as string)) return false;
  const expectedUnlocated = new Map(unlocated.map((row) => [row.geo_id, row.geo_display_name]));
  if (value.unlocated_geographies.length !== expectedUnlocated.size || !value.unlocated_geographies.every((item) => expectedUnlocated.get((item as JsonRecord).geo_id) === (item as JsonRecord).geo_display_name)) return false;
  if (!budgetKey) return true;
  if (!nonNegative(value.located_budget_rub) || !nonNegative(value.unlocated_budget_rub)) return false;
  const locatedBudget = located.reduce((sum, row) => sum + (row[budgetKey] as number), 0);
  const unlocatedBudget = unlocated.reduce((sum, row) => sum + (row[budgetKey] as number), 0);
  if (!moneyNear(value.located_budget_rub, locatedBudget) || !moneyNear(value.unlocated_budget_rub, unlocatedBudget)) return false;
  const total = locatedBudget + unlocatedBudget;
  return total === 0 ? value.unlocated_budget_share === null : number(value.unlocated_budget_share) && shareNear(value.unlocated_budget_share, unlocatedBudget / total);
}
function quantiles(value: unknown, unit: string): boolean {
  if (!record(value) || !exact(value, QUANTILE_KEYS) || value.unit !== unit || !text(value.display_text) || !enumValue(value.status, ["available", "unavailable"] as const)) return false;
  if (value.status === "unavailable") return value.p10 === null && value.p50 === null && value.p90 === null;
  return number(value.p10) && number(value.p50) && number(value.p90) && value.p10 <= value.p50 && value.p50 <= value.p90;
}
function ratioMatchesTurnover(turnover: JsonRecord, ratio: JsonRecord, denominator: number): boolean {
  if (turnover.status !== "available" || denominator <= 0) return ratio.status === "unavailable";
  if (ratio.status !== "available") return false;
  return (["p10", "p50", "p90"] as const).every((key) =>
    Math.abs((ratio[key] as number) - (turnover[key] as number) / denominator) <= SHARE_TOLERANCE,
  );
}
function budget(value: unknown, requested: number): boolean {
  if (!record(value) || !exact(value, BUDGET_KEYS) || !nonNegative(value.requested_budget_rub) || !moneyNear(value.requested_budget_rub, requested) || !nonNegative(value.allocated_budget_rub) || !nonNegative(value.unallocated_budget_rub) || !moneyNear(value.allocated_budget_rub + value.unallocated_budget_rub, value.requested_budget_rub)) return false;
  if ((value.requested_budget_rub as number) === 0) return value.allocation_share === null;
  return number(value.allocation_share) && value.allocation_share >= -SHARE_TOLERANCE && value.allocation_share <= 1 + SHARE_TOLERANCE && shareNear(value.allocation_share, (value.allocated_budget_rub as number) / (value.requested_budget_rub as number));
}
function riskBudget(value: unknown, allocated: number): boolean {
  if (!record(value) || !exact(value, RISK_KEYS)) return false;
  const monies = [value.within_support_budget_rub, value.controlled_extrapolation_budget_rub, value.high_risk_budget_rub];
  const shares = [value.within_support_share, value.controlled_extrapolation_share, value.high_risk_share];
  const cells = [value.within_support_cells_n, value.controlled_extrapolation_cells_n, value.high_risk_cells_n];
  if (!monies.every(nonNegative) || !cells.every(nonNegativeInteger) || !moneyNear((monies[0] as number) + (monies[1] as number) + (monies[2] as number), allocated)) return false;
  if (allocated === 0) return shares.every((share) => share === null);
  return shares.every((share) => number(share) && share >= -SHARE_TOLERANCE && share <= 1 + SHARE_TOLERANCE) && shareNear((shares[0] as number) + (shares[1] as number) + (shares[2] as number), 1) && monies.every((money, index) => shareNear((shares[index] as number), (money as number) / allocated));
}
function serving(value: unknown): boolean {
  return record(value) && exact(value, ["serving_policy_version", "target_id", "core_target", "serving_targets_n", "active_serving_models_n", "research_models_in_package_n", "calculation_allowed", "production_claim_allowed"]) && value.serving_policy_version === "turnover_serving_v1" && value.target_id === "turnover" && value.core_target === "turnover_per_user" && value.serving_targets_n === 1 && value.active_serving_models_n === 4 && value.research_models_in_package_n === 12 && typeof value.calculation_allowed === "boolean" && value.production_claim_allowed === false;
}
function evidence(value: unknown): boolean { return record(value) && exact(value, ["status", "generated_at_utc", "reason_code", "display_text"]) && enumValue(value.status, ["passed", "unavailable", "failed"] as const) && (value.generated_at_utc === null || isoDateTime(value.generated_at_utc)) && (value.reason_code === null || text(value.reason_code)) && text(value.display_text); }
function policy(value: unknown): boolean { return record(value) && exact(value, ["segment", "channel_id", "channel_display_name", "target", "allowed_use", "forecast_action", "optimizer_action", "display_text"]) && text(value.segment) && channel({ channel_id: value.channel_id, channel_display_name: value.channel_display_name }) && value.target === "turnover" && text(value.allowed_use) && text(value.forecast_action) && text(value.optimizer_action) && text(value.display_text); }
function statusRow(value: unknown): boolean { return record(value) && exact(value, ["code", "display_text"]) && text(value.code) && text(value.display_text); }

export function parseJobResultViewV2(value: unknown, expectedJobId: string): JobResultViewV2 {
  if (!record(value) || !exact(value, RESULT_KEYS) || value.contract_name !== "job_result_view_v2" || value.schema_version !== "2.0.0" || !enumValue(value.record_origin, ["application_runtime", "sanitized_fixture"] as const) || !text(value.job_id) || value.job_id !== expectedJobId || !text(value.result_id) || !text(value.source_overview_id) || !isoDateTime(value.updated_at_utc) || hasUnsafeString(value)) throw new UnsupportedBusinessSemanticsContractError();
  if (!record(value.campaign) || !exact(value.campaign, RESULT_CAMPAIGN_KEYS) || !text(value.campaign.campaign_id) || !text(value.campaign.campaign_name) || !uniqueStrings(value.campaign.segments) || !isoDate(value.campaign.start_date) || !isoDate(value.campaign.end_date) || value.campaign.start_date > value.campaign.end_date || !nonNegative(value.campaign.requested_budget_rub) || !Array.isArray(value.campaign.channels) || !value.campaign.channels.every(channel) || !uniqueBy(value.campaign.channels, (item) => (item as JsonRecord).channel_id as string) || !nonNegativeInteger(value.campaign.geographies_n) || !Array.isArray(value.campaign.geographies) || value.campaign.geographies_n !== value.campaign.geographies.length || !value.campaign.geographies.every((item) => geo(item)) || !uniqueBy(value.campaign.geographies, (item) => (item as JsonRecord).geo_id as string) || !uniqueBy(value.campaign.geographies, (item) => (item as JsonRecord).geo_display_name as string)) throw new UnsupportedBusinessSemanticsContractError();
  const requested = value.campaign.requested_budget_rub as number;
  if (!Array.isArray(value.scenarios) || value.scenarios.length !== SCENARIOS.length) throw new UnsupportedBusinessSemanticsContractError();
  const scenarios = value.scenarios as JsonRecord[];
  scenarios.forEach((scenario, index) => validateScenario(scenario, SCENARIOS[index], requested));
  const recommended = scenarios.filter((scenario) => scenario.is_recommended);
  if (!record(value.recommendation) || !exact(value.recommendation, RESULT_RECOMMENDATION_KEYS) || !enumValue(value.recommendation.decision_status, ["recommended_reallocation", "keep_uploaded_plan", "manual_review_required", "no_safe_recommendation", "unavailable"] as const) || !enumValue(value.recommendation.review_status, ["not_required", "manual_review_required"] as const) || !text(value.recommendation.title) || !text(value.recommendation.display_text) || !text(value.recommendation.decision_scope_text)) throw new UnsupportedBusinessSemanticsContractError();
  const chosen = value.recommendation.scenario_id;
  if (!enumValue(chosen, SCENARIOS)) throw new UnsupportedBusinessSemanticsContractError();
  const selected = scenarios.find((scenario) => scenario.scenario_id === chosen);
  if (!selected) throw new UnsupportedBusinessSemanticsContractError();
  if (value.recommendation.decision_status === "recommended_reallocation") {
    if (value.recommendation.review_status !== "not_required" || recommended.length !== 1 || chosen !== recommended[0].scenario_id || chosen === "S01" || selected.status !== "completed" || selected.decision_status !== "recommended_reallocation" || (selected.budget as JsonRecord).unallocated_budget_rub as number > MONEY_TOLERANCE_RUB || ((selected.risk_budget as JsonRecord).high_risk_budget_rub as number) > MONEY_TOLERANCE_RUB) throw new UnsupportedBusinessSemanticsContractError();
  } else {
    if (recommended.length !== 0) throw new UnsupportedBusinessSemanticsContractError();
    if (value.recommendation.decision_status === "keep_uploaded_plan" && (chosen !== "S01" || value.recommendation.review_status !== "manual_review_required")) throw new UnsupportedBusinessSemanticsContractError();
    if (value.recommendation.decision_status === "no_safe_recommendation" && (chosen !== "S05" || selected.scenario_variant !== "safe_partial" || value.recommendation.review_status !== "manual_review_required")) throw new UnsupportedBusinessSemanticsContractError();
  }
  if (!record(value.media_plan) || !exact(value.media_plan, ["endpoint", "selected_scenario_id"]) || value.media_plan.endpoint !== `/api/v1/jobs/${expectedJobId}/media-plan-v2` || value.media_plan.selected_scenario_id !== chosen) throw new UnsupportedBusinessSemanticsContractError();
  if (!record(value.map) || !exact(value.map, ["status", "display_text", "coordinate_catalog_version", "geo_points"]) || !enumValue(value.map.status, ["available", "partial", "unavailable"] as const) || !text(value.map.display_text) || !text(value.map.coordinate_catalog_version) || !Array.isArray(value.map.geo_points) || value.map.geo_points.length !== value.campaign.geographies.length || !value.map.geo_points.every((item) => geo(item, true)) || !uniqueBy(value.map.geo_points, (item) => (item as JsonRecord).geo_id as string)) throw new UnsupportedBusinessSemanticsContractError();
  const campaignGeoNames = new Map(value.campaign.geographies.map((item) => [(item as JsonRecord).geo_id, (item as JsonRecord).geo_display_name]));
  if (!value.map.geo_points.every((item) => campaignGeoNames.get((item as JsonRecord).geo_id) === (item as JsonRecord).geo_display_name)) throw new UnsupportedBusinessSemanticsContractError();
  const locatedPoints = value.map.geo_points.filter((item) => (item as JsonRecord).coordinates_status === "canonical").length;
  const expectedMapStatus = value.map.geo_points.length > 0 && locatedPoints === value.map.geo_points.length ? "available" : locatedPoints > 0 ? "partial" : "unavailable";
  if (value.map.status !== expectedMapStatus) throw new UnsupportedBusinessSemanticsContractError();
  if (!Array.isArray(value.limitations) || !value.limitations.every(statusRow)) throw new UnsupportedBusinessSemanticsContractError();
  return value as unknown as JobResultViewV2;
}

function validateScenario(value: JsonRecord, id: ScenarioId, requested: number): void {
  if (!exact(value, RESULT_SCENARIO_KEYS) || value.scenario_id !== id || !text(value.name) || !text(value.description) || !enumValue(value.scenario_kind, ["uploaded_plan", "benchmark_plan", "conservative_plan", "optimized_plan"] as const) || (value.scenario_variant !== null && !text(value.scenario_variant)) || !enumValue(value.status, ["completed", "infeasible", "unavailable"] as const) || typeof value.is_recommended !== "boolean" || !enumValue(value.decision_status, ["recommended_reallocation", "keep_uploaded_plan", "manual_review_required", "no_safe_recommendation", "unavailable"] as const) || !enumValue(value.review_status, ["not_required", "manual_review_required"] as const) || !budget(value.budget, requested) || !record(value.budget) || !quantiles(value.incremental_turnover, "RUB") || !record(value.roas) || !exact(value.roas, ROAS_KEYS) || !quantiles(value.roas.allocated_budget, "ratio") || !quantiles(value.roas.requested_budget, "ratio") || !enumValue(value.roas.primary_denominator_kind, ["allocated_budget", "requested_budget"] as const) || !number(value.roas.primary_denominator_budget_rub) || !riskBudget(value.risk_budget, value.budget.allocated_budget_rub as number) || !record(value.reliability) || !exact(value.reliability, RELIABILITY_KEYS) || !enumValue(value.reliability.status, ["within_support", "controlled_extrapolation", "high_risk", "manual_review", "unavailable"] as const) || !text(value.reliability.display_text) || !uniqueStrings(value.reliability.evidence_codes, false) || !positiveIntegerOrNull(value.reliability.safe_rank) || !positiveIntegerOrNull(value.reliability.raw_rank) || !uniqueStrings(value.limiting_constraints, false)) throw new UnsupportedBusinessSemanticsContractError();
  const primaryBudget = value.roas.primary_denominator_kind === "allocated_budget" ? value.budget.allocated_budget_rub : value.budget.requested_budget_rub;
  if (!moneyNear(value.roas.primary_denominator_budget_rub, primaryBudget as number)) throw new UnsupportedBusinessSemanticsContractError();
  const turnover = value.incremental_turnover as JsonRecord;
  const roas = value.roas as JsonRecord;
  const allocatedRoas = roas.allocated_budget as JsonRecord;
  const requestedRoas = roas.requested_budget as JsonRecord;
  if (value.status === "completed") {
    if (turnover.status !== "available") throw new UnsupportedBusinessSemanticsContractError();
  } else if (turnover.status !== "unavailable" || allocatedRoas.status !== "unavailable" || requestedRoas.status !== "unavailable") throw new UnsupportedBusinessSemanticsContractError();
  if (!ratioMatchesTurnover(turnover, allocatedRoas, value.budget.allocated_budget_rub as number) || !ratioMatchesTurnover(turnover, requestedRoas, value.budget.requested_budget_rub as number)) throw new UnsupportedBusinessSemanticsContractError();
  if (id === "S01" && (value.scenario_kind !== "uploaded_plan" || value.decision_status !== "keep_uploaded_plan" || value.review_status !== "manual_review_required" || value.is_recommended)) throw new UnsupportedBusinessSemanticsContractError();
  if (id === "S05") {
    if (value.scenario_kind !== "conservative_plan" || !["full_conservative", "safe_partial"].includes(value.scenario_variant as string)) throw new UnsupportedBusinessSemanticsContractError();
    if (value.scenario_variant === "full_conservative" && ((value.budget.unallocated_budget_rub as number) > MONEY_TOLERANCE_RUB || ((value.risk_budget as JsonRecord).high_risk_budget_rub as number) > MONEY_TOLERANCE_RUB)) throw new UnsupportedBusinessSemanticsContractError();
    if (value.scenario_variant === "safe_partial" && (value.is_recommended || value.decision_status !== "no_safe_recommendation" || value.review_status !== "manual_review_required" || (value.budget.unallocated_budget_rub as number) <= MONEY_TOLERANCE_RUB || value.limiting_constraints.length === 0)) throw new UnsupportedBusinessSemanticsContractError();
  }
  if (id === "S06") {
    if (value.scenario_kind !== "optimized_plan") throw new UnsupportedBusinessSemanticsContractError();
    if (value.status === "completed") {
      if ((value.budget.unallocated_budget_rub as number) > MONEY_TOLERANCE_RUB || (value.is_recommended && ((value.risk_budget as JsonRecord).high_risk_budget_rub as number) > MONEY_TOLERANCE_RUB)) throw new UnsupportedBusinessSemanticsContractError();
    } else if ((value.budget.allocated_budget_rub as number) > MONEY_TOLERANCE_RUB || value.is_recommended || value.decision_status !== "unavailable" || value.review_status !== "manual_review_required" || value.limiting_constraints.length === 0) throw new UnsupportedBusinessSemanticsContractError();
  }
}

export function parseScenarioMediaPlanV2(value: unknown, expectedJobId: string, query: ScenarioMediaPlanV2Query, expectedResult: JobResultViewV2): ScenarioMediaPlanV2 {
  const expectedScenario = expectedResult.scenarios.find((scenario) => scenario.scenario_id === query.scenarioId);
  const sourceScenario = expectedResult.scenarios.find((scenario) => scenario.scenario_id === "S01");
  if (expectedResult.job_id !== expectedJobId || !expectedScenario || !sourceScenario) throw new UnsupportedBusinessSemanticsContractError();
  if (!record(value) || !exact(value, PLAN_KEYS) || value.contract_name !== "scenario_media_plan_v2" || value.schema_version !== "2.0.0" || !enumValue(value.record_origin, ["application_runtime", "sanitized_fixture"] as const) || value.job_id !== expectedJobId || !text(value.result_id) || !text(value.campaign_id) || value.grain !== "geo_channel_total" || !isoDateTime(value.updated_at_utc) || hasUnsafeString(value)) throw new UnsupportedBusinessSemanticsContractError();
  if (value.result_id !== expectedResult.result_id || value.campaign_id !== expectedResult.campaign.campaign_id) throw new UnsupportedBusinessSemanticsContractError();
  if (!record(value.scenario) || !exact(value.scenario, ["scenario_id", "title", "status", "is_selected", "safe_rank", "raw_rank", "quality_status", "quality_display_text"]) || value.scenario.scenario_id !== query.scenarioId || !text(value.scenario.title) || !enumValue(value.scenario.status, ["completed", "unavailable"] as const) || typeof value.scenario.is_selected !== "boolean" || !positiveIntegerOrNull(value.scenario.safe_rank) || !positiveIntegerOrNull(value.scenario.raw_rank) || !text(value.scenario.quality_status) || !text(value.scenario.quality_display_text)) throw new UnsupportedBusinessSemanticsContractError();
  if (value.scenario.status !== expectedScenario.status || value.scenario.is_selected !== (expectedResult.media_plan.selected_scenario_id === query.scenarioId) || value.scenario.safe_rank !== expectedScenario.reliability.safe_rank || value.scenario.raw_rank !== expectedScenario.reliability.raw_rank) throw new UnsupportedBusinessSemanticsContractError();
  if (!record(value.filters) || !exact(value.filters, ["channel_id", "geo_display_name", "date"]) || value.filters.date !== null || value.filters.channel_id !== (query.channel ?? null) || value.filters.geo_display_name !== (query.geo ?? null) || (value.filters.channel_id !== null && !(value.filters.channel_id as string in CHANNEL_DISPLAY_NAMES))) throw new UnsupportedBusinessSemanticsContractError();
  const page = query.page ?? 1; const pageSize = query.pageSize ?? 100;
  if (!record(value.pagination) || !exact(value.pagination, ["page", "page_size", "total_rows", "total_pages"]) || value.pagination.page !== page || value.pagination.page_size !== pageSize || !nonNegativeInteger(value.pagination.total_rows) || !nonNegativeInteger(value.pagination.total_pages) || value.pagination.total_pages !== Math.ceil(value.pagination.total_rows / pageSize) || value.rows === undefined || !Array.isArray(value.rows) || value.rows.length > pageSize) throw new UnsupportedBusinessSemanticsContractError();
  if (!record(value.totals) || !exact(value.totals, ["requested_budget_rub", "source_budget_rub", "selected_budget_rub", "unallocated_budget_rub", "delta_rub", "reconciliation_status"]) || !nonNegative(value.totals.requested_budget_rub) || !nonNegative(value.totals.source_budget_rub) || !nonNegative(value.totals.selected_budget_rub) || !nonNegative(value.totals.unallocated_budget_rub) || !number(value.totals.delta_rub) || value.totals.reconciliation_status !== "reconciled" || !moneyNear(value.totals.selected_budget_rub + value.totals.unallocated_budget_rub, value.totals.requested_budget_rub) || !moneyNear(value.totals.delta_rub, value.totals.selected_budget_rub - value.totals.source_budget_rub)) throw new UnsupportedBusinessSemanticsContractError();
  if (!moneyNear(value.totals.requested_budget_rub, expectedResult.campaign.requested_budget_rub) || !moneyNear(value.totals.source_budget_rub, sourceScenario.budget.allocated_budget_rub) || !moneyNear(value.totals.selected_budget_rub, expectedScenario.budget.allocated_budget_rub) || !moneyNear(value.totals.unallocated_budget_rub, expectedScenario.budget.unallocated_budget_rub)) throw new UnsupportedBusinessSemanticsContractError();
  if (!record(value.filtered_totals) || !exact(value.filtered_totals, ["source_budget_rub", "selected_budget_rub", "delta_rub"]) || !nonNegative(value.filtered_totals.source_budget_rub) || !nonNegative(value.filtered_totals.selected_budget_rub) || !number(value.filtered_totals.delta_rub) || !moneyNear(value.filtered_totals.delta_rub, value.filtered_totals.selected_budget_rub - value.filtered_totals.source_budget_rub)) throw new UnsupportedBusinessSemanticsContractError();
  const rows = value.rows as JsonRecord[];
  if (!rows.every((row) => mediaRow(row, value.campaign_id as string, query.scenarioId)) || !uniqueBy(rows, (row) => `${row.segment}\u0000${row.geo_id}\u0000${row.channel_id}`)) throw new UnsupportedBusinessSemanticsContractError();
  const source = rows.reduce((sum, row) => sum + (row.source_budget_rub as number), 0); const selected = rows.reduce((sum, row) => sum + (row.selected_budget_rub as number), 0);
  if (source > (value.filtered_totals.source_budget_rub as number) + MONEY_TOLERANCE_RUB || selected > (value.filtered_totals.selected_budget_rub as number) + MONEY_TOLERANCE_RUB || (value.pagination.total_rows === rows.length && (!moneyNear(source, value.filtered_totals.source_budget_rub as number) || !moneyNear(selected, value.filtered_totals.selected_budget_rub as number)))) throw new UnsupportedBusinessSemanticsContractError();
  if (!aggregates(value.aggregates, value.totals)) throw new UnsupportedBusinessSemanticsContractError();
  if (!record(value.map) || !exact(value.map, ["status", "display_text", "geo_points", "coordinate_catalog_version"]) || value.map.status !== "unavailable" || !text(value.map.display_text) || value.map.geo_points !== null || value.map.coordinate_catalog_version !== null) throw new UnsupportedBusinessSemanticsContractError();
  if (!record(value.source_artifact) || !exact(value.source_artifact, ["artifact_id", "kind", "sha256"]) || !OPAQUE_ID.test(String(value.source_artifact.artifact_id)) || value.source_artifact.kind !== "recommended_allocations_csv" || !SHA256.test(String(value.source_artifact.sha256)) || !artifactAvailability(value.working_media_plan) || !Array.isArray(value.limitations) || !value.limitations.every(statusRow)) throw new UnsupportedBusinessSemanticsContractError();
  return value as unknown as ScenarioMediaPlanV2;
}
function mediaRow(value: JsonRecord, campaignId: string, scenarioId: ScenarioId): boolean { return exact(value, ["scenario_id", "campaign_id", "segment", "geo_id", "geo_display_name", "channel_id", "channel_display_name", "date", "source_budget_rub", "selected_budget_rub", "delta_rub", "delta_pct", "source_budget_share", "selected_budget_share", "quality_status", "quality_display_text"]) && value.scenario_id === scenarioId && value.campaign_id === campaignId && text(value.segment) && geo({ geo_id: value.geo_id, geo_display_name: value.geo_display_name }) && channel({ channel_id: value.channel_id, channel_display_name: value.channel_display_name }) && value.date === null && nonNegative(value.source_budget_rub) && nonNegative(value.selected_budget_rub) && number(value.delta_rub) && moneyNear(value.delta_rub, value.selected_budget_rub - value.source_budget_rub) && (value.delta_pct === null || number(value.delta_pct)) && number(value.source_budget_share) && value.source_budget_share >= -SHARE_TOLERANCE && value.source_budget_share <= 1 + SHARE_TOLERANCE && number(value.selected_budget_share) && value.selected_budget_share >= -SHARE_TOLERANCE && value.selected_budget_share <= 1 + SHARE_TOLERANCE && text(value.quality_status) && text(value.quality_display_text); }
function aggregateRow(value: unknown, geoRequired: boolean, channelRequired: boolean): boolean { if (!record(value)) return false; const keys = [...(geoRequired ? ["geo_id", "geo_display_name"] : []), ...(channelRequired ? ["channel_id", "channel_display_name"] : []), "source_budget_rub", "selected_budget_rub", "delta_rub", "delta_pct", "quality_status", "quality_display_text"]; return exact(value, keys) && (!geoRequired || geo({ geo_id: value.geo_id, geo_display_name: value.geo_display_name })) && (!channelRequired || channel({ channel_id: value.channel_id, channel_display_name: value.channel_display_name })) && nonNegative(value.source_budget_rub) && nonNegative(value.selected_budget_rub) && number(value.delta_rub) && moneyNear(value.delta_rub, value.selected_budget_rub - value.source_budget_rub) && (value.delta_pct === null || number(value.delta_pct)) && text(value.quality_status) && text(value.quality_display_text); }
function aggregates(value: unknown, totals: JsonRecord): boolean { if (!record(value) || !exact(value, ["by_channel", "by_geo", "by_geo_channel", "by_date", "channel_date_matrix", "geo_channel_matrix"]) || !Array.isArray(value.by_channel) || !Array.isArray(value.by_geo) || !Array.isArray(value.by_geo_channel) || !value.by_channel.every((item) => aggregateRow(item, false, true)) || !value.by_geo.every((item) => aggregateRow(item, true, false)) || !value.by_geo_channel.every((item) => aggregateRow(item, true, true))) return false; const sum = (items: unknown[]): { source: number; selected: number } => items.reduce<{ source: number; selected: number }>((acc, item) => ({ source: acc.source + ((item as JsonRecord).source_budget_rub as number), selected: acc.selected + ((item as JsonRecord).selected_budget_rub as number) }), { source: 0, selected: 0 }); for (const items of [value.by_channel, value.by_geo, value.by_geo_channel] as unknown[][]) { const actual = sum(items); if (!moneyNear(actual.source, totals.source_budget_rub as number) || !moneyNear(actual.selected, totals.selected_budget_rub as number)) return false; } const unavailable = (item: unknown) => record(item) && exact(item, ["status", "display_text", "rows"]) && item.status === "unavailable" && text(item.display_text) && item.rows === null; return unavailable(value.by_date) && unavailable(value.channel_date_matrix) && record(value.geo_channel_matrix) && exact(value.geo_channel_matrix, ["status", "display_text", "rows"]) && value.geo_channel_matrix.status === "ready" && text(value.geo_channel_matrix.display_text) && Array.isArray(value.geo_channel_matrix.rows) && value.geo_channel_matrix.rows.every((item) => aggregateRow(item, true, true)) && moneyNear((totals.selected_budget_rub as number) + (totals.unallocated_budget_rub as number), totals.requested_budget_rub as number); }
function artifactAvailability(value: unknown): boolean { return record(value) && exact(value, ["status", "display_text", "artifact"]) && text(value.display_text) && ((value.status === "unavailable" && value.artifact === null) || (value.status === "available" && record(value.artifact))); }

export function parseValidationViewV2(value: unknown, expectedValidationId: string): ValidationResultV2 {
  if (!record(value) || !exact(value, VALIDATION_KEYS) || value.contract_name !== "validation_result_v2" || value.schema_version !== "2.0.0" || value.validation_id !== expectedValidationId || !enumValue(value.status, ["passed", "warning", "failed", "unavailable"] as const) || typeof value.job_creation_allowed !== "boolean" || hasUnsafeString(value)) throw new UnsupportedBusinessSemanticsContractError();
  if (!record(value.file_validation) || !exact(value.file_validation, ["status", "rows_n", "campaigns_n", "geographies_n", "channels_n", "requested_budget_rub", "blocking_errors_n", "warnings_n", "checks"]) || !enumValue(value.file_validation.status, ["passed", "warning", "failed", "unavailable"] as const) || ![value.file_validation.rows_n, value.file_validation.campaigns_n, value.file_validation.geographies_n, value.file_validation.channels_n, value.file_validation.blocking_errors_n, value.file_validation.warnings_n].every(nonNegativeInteger) || !nonNegative(value.file_validation.requested_budget_rub) || !Array.isArray(value.file_validation.checks) || !value.file_validation.checks.every((item) => record(item) && exact(item, ["code", "status", "display_text"]) && text(item.code) && enumValue(item.status, ["passed", "warning", "failed", "unavailable"] as const) && text(item.display_text))) throw new UnsupportedBusinessSemanticsContractError();
  const fileValidation = value.file_validation;
  if (value.job_creation_allowed && value.file_validation.status === "failed") throw new UnsupportedBusinessSemanticsContractError();
  if (!Array.isArray(value.model_limitations) || !value.model_limitations.every(validationLimitation) || !uniqueBy(value.model_limitations, (item) => { const row = item as JsonRecord; return `${row.target}\u0000${row.channel_id}\u0000${row.limitation_type}`; })) throw new UnsupportedBusinessSemanticsContractError();
  if (!Array.isArray(value.geo_points) || value.geo_points.length !== fileValidation.geographies_n || !value.geo_points.every((item) => validationGeo(item, fileValidation.requested_budget_rub as number)) || !uniqueBy(value.geo_points, (item) => (item as JsonRecord).geo_id as string) || !uniqueBy(value.geo_points, (item) => (item as JsonRecord).geo_display_name as string)) throw new UnsupportedBusinessSemanticsContractError();
  const geoBudget = (value.geo_points as JsonRecord[]).reduce((sum, geoPoint) => sum + (geoPoint.budget_rub as number), 0);
  if (!moneyNear(geoBudget, fileValidation.requested_budget_rub as number) || !mapCoverage(value.map_coverage, value.geo_points as JsonRecord[], "budget_rub")) throw new UnsupportedBusinessSemanticsContractError();
  return value as unknown as ValidationResultV2;
}
function validationLimitation(value: unknown): boolean { return record(value) && exact(value, ["target", "channel_id", "channel_display_name", "limitation_type", "affected_geos_n", "affected_geos", "severity", "allowed_use", "blocks_calculation", "what", "why", "recommended_action"]) && value.target === "turnover" && channel({ channel_id: value.channel_id, channel_display_name: value.channel_display_name }) && text(value.limitation_type) && nonNegativeInteger(value.affected_geos_n) && uniqueStrings(value.affected_geos, false) && value.affected_geos_n === value.affected_geos.length && !value.affected_geos.some((item) => TRUNCATED_GEOS.test(item)) && enumValue(value.severity, ["information", "warning", "manual_review", "blocking"] as const) && enumValue(value.allowed_use, ["primary", "caution", "diagnostic", "unsupported", "unavailable"] as const) && typeof value.blocks_calculation === "boolean" && text(value.what) && text(value.why) && text(value.recommended_action); }
function validationGeo(value: unknown, requested: number): boolean {
  if (!record(value) || !exact(value, ["geo_id", "geo_display_name", "input_geo_name", "canonical_geo_id", "canonical_geo_display_name", "normalization_status", "normalization_rule", "latitude", "longitude", "coordinates_status", "region_id", "region_display_name", "budget_rub", "budget_share", "channels", "has_model_limitations", "model_limitations_n"]) || !geo({ geo_id: value.geo_id, geo_display_name: value.geo_display_name, latitude: value.latitude, longitude: value.longitude, coordinates_status: value.coordinates_status, region_id: value.region_id, region_display_name: value.region_display_name }, true) || !text(value.input_geo_name) || !enumValue(value.normalization_status, ["canonical", "alias", "unknown", "ambiguous"] as const) || !text(value.normalization_rule) || !nonNegative(value.budget_rub) || !Array.isArray(value.channels) || !value.channels.every(channel) || !uniqueBy(value.channels, (item) => (item as JsonRecord).channel_id as string) || typeof value.has_model_limitations !== "boolean" || !nonNegativeInteger(value.model_limitations_n) || value.has_model_limitations !== (value.model_limitations_n > 0)) return false;
  if (value.normalization_status === "canonical" || value.normalization_status === "alias") {
    if (value.canonical_geo_id !== value.geo_id || value.canonical_geo_display_name !== value.geo_display_name || value.coordinates_status !== "canonical") return false;
  } else if (value.canonical_geo_id !== null || value.canonical_geo_display_name !== null || value.coordinates_status !== "unavailable") return false;
  if (requested === 0) return value.budget_share === null;
  return number(value.budget_share) && value.budget_share >= -SHARE_TOLERANCE && value.budget_share <= 1 + SHARE_TOLERANCE && shareNear(value.budget_share, value.budget_rub / requested);
}

export function parseActiveModelPassportV2(value: unknown): ModelPassportV2 { if (!record(value) || !exact(value, PASSPORT_KEYS) || value.contract_name !== "model_passport_v2" || value.schema_version !== "2.0.0" || !enumValue(value.record_origin, ["verified_model_package", "synthetic_fixture"] as const) || !serving(value.serving) || hasUnsafeString(value)) throw new UnsupportedBusinessSemanticsContractError(); if (!record(value.package) || !exact(value.package, ["registry_channel", "registry_event_id", "package_id", "package_fingerprint", "model_run_id", "package_stage", "activation_status", "package_schema_version", "gate_policy_version"]) || !Object.values(value.package).every(text) || !PACKAGE_ID.test(String(value.package.package_id)) || !SHA256.test(String(value.package.package_fingerprint))) throw new UnsupportedBusinessSemanticsContractError(); if (!record(value.data) || !exact(value.data, ["grain", "training_period", "development_shadow_period"]) || value.data.grain !== "daily" || !period(value.data.training_period) || !shadowPeriod(value.data.development_shadow_period)) throw new UnsupportedBusinessSemanticsContractError(); if (!record(value.coverage) || !exact(value.coverage, ["segments", "channels", "targets", "geographies_n", "capability_cells_n"]) || !uniqueStrings(value.coverage.segments) || !Array.isArray(value.coverage.channels) || !value.coverage.channels.every(channel) || !uniqueBy(value.coverage.channels, (item) => (item as JsonRecord).channel_id as string) || !Array.isArray(value.coverage.targets) || value.coverage.targets.length !== 1 || !record(value.coverage.targets[0]) || !exact(value.coverage.targets[0], ["target_id", "core_target"]) || value.coverage.targets[0].target_id !== "turnover" || value.coverage.targets[0].core_target !== "turnover_per_user" || !nonNegativeInteger(value.coverage.geographies_n) || !nonNegativeInteger(value.coverage.capability_cells_n)) throw new UnsupportedBusinessSemanticsContractError(); if (!record(value.validation) || !exact(value.validation, ["historical_replay", "sealed_oot", "production_blockers"]) || !evidence(value.validation.historical_replay) || !evidence(value.validation.sealed_oot) || !Array.isArray(value.validation.production_blockers) || !value.validation.production_blockers.every(statusRow) || !Array.isArray(value.channel_policies) || !value.channel_policies.every(policy) || !Array.isArray(value.caveats) || !value.caveats.every(statusRow)) throw new UnsupportedBusinessSemanticsContractError(); return value as unknown as ModelPassportV2; }
function period(value: unknown): boolean { return record(value) && exact(value, ["start_date", "end_date"]) && isoDate(value.start_date) && isoDate(value.end_date) && value.start_date <= value.end_date; }
function shadowPeriod(value: unknown): boolean { return record(value) && exact(value, ["start_date", "end_date", "purpose"]) && value.purpose === "development_shadow_not_sealed_oot" && ((value.start_date === null && value.end_date === null) || (isoDate(value.start_date) && isoDate(value.end_date) && value.start_date <= value.end_date)); }

export function parseModelOverviewV2(value: unknown): ModelOverviewV2 { if (!record(value) || !exact(value, OVERVIEW_KEYS) || value.contract_name !== "model_overview_v2" || value.schema_version !== "2.0.0" || !serving(value.serving) || hasUnsafeString(value) || !record(value.summary) || !exact(value.summary, ["training_period", "package_status", "activation_status", "calculation_allowed", "historical_replay", "sealed_oot"]) || !period(value.summary.training_period) || (value.summary.package_status !== null && !text(value.summary.package_status)) || (value.summary.activation_status !== null && !text(value.summary.activation_status)) || value.summary.calculation_allowed !== (value.serving as JsonRecord).calculation_allowed || !evidence(value.summary.historical_replay) || !evidence(value.summary.sealed_oot) || !Array.isArray(value.channel_policies) || !value.channel_policies.every(policy) || !Array.isArray(value.limitations) || !value.limitations.every((item) => record(item) && Object.keys(item).every((key) => ["code", "display_text", "status", "title", "recommended_action"].includes(key)) && text(item.code) && text(item.display_text) && Object.values(item).every((entry) => typeof entry === "string"))) throw new UnsupportedBusinessSemanticsContractError(); return value as unknown as ModelOverviewV2; }

export function parseGeoCatalog(value: unknown): GeoCatalogV1 { if (!record(value) || !exact(value, CATALOG_KEYS) || value.contract_name !== "geo_catalog_v1" || value.schema_version !== "1.0.0" || !text(value.catalog_version) || !text(value.coordinates_source) || !text(value.coordinates_source_version_or_date) || value.coordinates_license !== "CC BY 4.0" || !enumValue(value.status, ["available", "partial", "unavailable"] as const) || !text(value.display_text) || !nonNegativeInteger(value.geographies_n) || !Array.isArray(value.entries) || value.entries.length !== value.geographies_n || !value.entries.every((item) => geo(item, true)) || !uniqueBy(value.entries, (item) => (item as JsonRecord).geo_id as string) || !uniqueBy(value.entries, (item) => (item as JsonRecord).geo_display_name as string) || !mapCoverage(value.coverage, value.entries as JsonRecord[]) || (value.coverage as JsonRecord).status !== value.status || hasUnsafeString(value)) throw new UnsupportedBusinessSemanticsContractError(); return value as unknown as GeoCatalogV1; }
export function parseWorkspaceGeoBudget(value: unknown): WorkspaceGeoBudgetV1 { if (!record(value) || !exact(value, WORKSPACE_KEYS) || value.contract_name !== "workspace_geo_budget_v1" || value.schema_version !== "1.0.0" || !text(value.catalog_version) || !enumValue(value.status, ["available", "partial", "unavailable"] as const) || !text(value.display_text) || !nonNegative(value.total_budget_rub) || !nonNegativeInteger(value.campaigns_n) || !nonNegativeInteger(value.geographies_n) || !Array.isArray(value.rows) || value.rows.length !== value.geographies_n || !value.rows.every(workspaceGeo) || !uniqueBy(value.rows, (item) => (item as JsonRecord).geo_id as string) || !uniqueBy(value.rows, (item) => (item as JsonRecord).geo_display_name as string) || !mapCoverage(value.coverage, value.rows as JsonRecord[], "total_budget_rub") || (value.coverage as JsonRecord).status !== value.status || hasUnsafeString(value)) throw new UnsupportedBusinessSemanticsContractError(); const total = (value.rows as JsonRecord[]).reduce((sum, row) => sum + (row.total_budget_rub as number), 0); if (!moneyNear(total, value.total_budget_rub as number)) throw new UnsupportedBusinessSemanticsContractError(); if ((value.total_budget_rub as number) === 0 ? !(value.rows as JsonRecord[]).every((row) => row.budget_share === null) : !(value.rows as JsonRecord[]).every((row) => number(row.budget_share) && shareNear(row.budget_share as number, (row.total_budget_rub as number) / (value.total_budget_rub as number)))) throw new UnsupportedBusinessSemanticsContractError(); return value as unknown as WorkspaceGeoBudgetV1; }
function workspaceGeo(value: unknown): boolean { return record(value) && exact(value, ["geo_id", "geo_display_name", "latitude", "longitude", "coordinates_status", "region_id", "region_display_name", "total_budget_rub", "campaigns_n", "budget_share"]) && geo({ geo_id: value.geo_id, geo_display_name: value.geo_display_name, latitude: value.latitude, longitude: value.longitude, coordinates_status: value.coordinates_status, region_id: value.region_id, region_display_name: value.region_display_name }, true) && nonNegative(value.total_budget_rub) && nonNegativeInteger(value.campaigns_n) && (value.budget_share === null || (number(value.budget_share) && value.budget_share >= -SHARE_TOLERANCE && value.budget_share <= 1 + SHARE_TOLERANCE)); }

function errorCode(value: unknown): string | null { return record(value) && exact(value, ERROR_KEYS) && record(value.error) && exact(value.error, ERROR_DETAIL_KEYS) && text(value.error.code) && text(value.error.display_text) && typeof value.error.retryable === "boolean" && text(value.error.user_action) ? value.error.code : null; }
function queryString(query: ScenarioMediaPlanV2Query): string { const page = query.page ?? 1; const pageSize = query.pageSize ?? 100; if (!SCENARIOS.includes(query.scenarioId) || !positivePage(page) || !positivePage(pageSize) || (query.channel !== undefined && query.channel !== null && !text(query.channel)) || (query.geo !== undefined && query.geo !== null && !text(query.geo))) throw new BusinessSemanticsQueryError(); const params = new URLSearchParams({ scenario_id: query.scenarioId, page: String(page), page_size: String(pageSize) }); if (query.channel) params.set("channel", query.channel); if (query.geo) params.set("geo", query.geo); return params.toString(); }
function positivePage(value: unknown): value is number { return integer(value) && value >= 1; }
function url(baseUrl: string, path: string): string { return `${baseUrl.replace(/\/+$/, "")}${path}`; }
async function get<T>(path: string, parse: (value: unknown) => T, signal?: AbortSignal, baseUrl = appEnv.apiBaseUrl): Promise<T> { let response: Response; try { response = await credentialedFetch(url(baseUrl, path), { headers: { Accept: "application/json" }, signal }); } catch { throw new BusinessSemanticsRequestError(); } let payload: unknown; try { payload = await response.json(); } catch { if (response.ok) throw new UnsupportedBusinessSemanticsContractError(response.status); throw new BusinessSemanticsRequestError(response.status); } const code = errorCode(payload); if (!response.ok) { if (response.status === 404 && code === "RESOURCE_NOT_READY") throw new BusinessSemanticsNotReadyError(); if (response.status === 404) throw new BusinessSemanticsNotFoundError(); if (response.status === 422) throw new BusinessSemanticsQueryError(); if (response.status === 503 && code !== null) throw new BusinessSemanticsUnavailableError(); throw new BusinessSemanticsRequestError(response.status); } return parse(payload); }

export function getJobResultViewV2(jobId: string, signal?: AbortSignal, baseUrl = appEnv.apiBaseUrl): Promise<JobResultViewV2> { if (!text(jobId)) return Promise.reject(new BusinessSemanticsQueryError()); return get(`/api/v1/jobs/${encodeURIComponent(jobId)}/result-view-v2`, (value) => parseJobResultViewV2(value, jobId), signal, baseUrl); }
export function getScenarioMediaPlanV2(jobId: string, query: ScenarioMediaPlanV2Query, expectedResult: JobResultViewV2, signal?: AbortSignal, baseUrl = appEnv.apiBaseUrl): Promise<ScenarioMediaPlanV2> { if (!text(jobId)) return Promise.reject(new BusinessSemanticsQueryError()); try { const suffix = queryString(query); return get(`/api/v1/jobs/${encodeURIComponent(jobId)}/media-plan-v2?${suffix}`, (value) => parseScenarioMediaPlanV2(value, jobId, query, expectedResult), signal, baseUrl); } catch (error) { return Promise.reject(error); } }
export function getValidationViewV2(validationId: string, signal?: AbortSignal, baseUrl = appEnv.apiBaseUrl): Promise<ValidationResultV2> { if (!text(validationId)) return Promise.reject(new BusinessSemanticsQueryError()); return get(`/api/v1/validations/${encodeURIComponent(validationId)}/view-v2`, (value) => parseValidationViewV2(value, validationId), signal, baseUrl); }
export function getActiveModelPassportV2(signal?: AbortSignal, baseUrl = appEnv.apiBaseUrl): Promise<ModelPassportV2> { return get("/api/v1/models/active-v2", parseActiveModelPassportV2, signal, baseUrl); }
export function getModelOverviewV2(signal?: AbortSignal, baseUrl = appEnv.apiBaseUrl): Promise<ModelOverviewV2> { return get("/api/v1/model/overview-v2", parseModelOverviewV2, signal, baseUrl); }
export function getGeoCatalog(signal?: AbortSignal, baseUrl = appEnv.apiBaseUrl): Promise<GeoCatalogV1> { return get("/api/v1/meta/geo-catalog", parseGeoCatalog, signal, baseUrl); }
export function getWorkspaceGeoBudget(signal?: AbortSignal, baseUrl = appEnv.apiBaseUrl): Promise<WorkspaceGeoBudgetV1> { return get("/api/v1/workspace/geo-budget", parseWorkspaceGeoBudget, signal, baseUrl); }
