import type {
  JobResultViewV1,
  MetricUnit,
  QuantileMetric,
  Scenario,
  ScenarioId,
} from "../../shared/api/generated/job-result-view-v1";

export type ResultTabId = "overview" | "scenarios" | "media-plan" | "report";

export const RESULT_TABS: readonly {
  id: ResultTabId;
  label: string;
}[] = [
  { id: "overview", label: "Обзор" },
  { id: "scenarios", label: "Сценарии и надежность" },
  { id: "media-plan", label: "Медиаплан" },
  { id: "report", label: "Отчет" },
] as const;

export const DEFAULT_RESULT_TAB: ResultTabId = "overview";

export const SCENARIO_IDS = ["S01", "S02", "S03", "S04", "S05", "S06"] as const;

export type ScenarioPresentation = {
  shortLabel: string;
  fixedLabel: string | null;
  marker: string | null;
};

export const SCENARIO_PRESENTATION: Record<ScenarioId, ScenarioPresentation> = {
  S01: {
    shortLabel: "S1",
    fixedLabel: "Как загружено",
    marker: "Исходный план",
  },
  S02: { shortLabel: "S2", fixedLabel: null, marker: null },
  S03: { shortLabel: "S3", fixedLabel: null, marker: null },
  S04: { shortLabel: "S4", fixedLabel: null, marker: null },
  S05: {
    shortLabel: "S5",
    fixedLabel: "Устойчивый ориентир",
    marker: "Устойчивый ориентир",
  },
  S06: { shortLabel: "S6", fixedLabel: null, marker: null },
};

export type ScenarioMetricId = keyof Scenario["metrics"];

export type ScenarioMetricDefinition = {
  id: ScenarioMetricId;
  label: string;
  shortLabel: string;
  diagnostic: boolean;
};

export const SCENARIO_METRICS: readonly ScenarioMetricDefinition[] = [
  {
    id: "incremental_turnover_rub",
    label: "Дополнительный оборот",
    shortLabel: "Доп. оборот",
    diagnostic: false,
  },
  {
    id: "roas",
    label: "ROAS по дополнительному обороту",
    shortLabel: "ROAS",
    diagnostic: false,
  },
  {
    id: "incremental_orders",
    label: "Дополнительные заказы",
    shortLabel: "Доп. заказы",
    diagnostic: true,
  },
  {
    id: "orders_per_100k_rub",
    label: "Заказы на 100 000 ₽",
    shortLabel: "Заказы на 100 000 ₽",
    diagnostic: true,
  },
  {
    id: "avg_basket_turnover_bridge_rub",
    label: "Вклад механизма среднего чека в дополнительный оборот",
    shortLabel: "Вклад механизма чека",
    diagnostic: true,
  },
] as const;

const resultTabIds = new Set<ResultTabId>(RESULT_TABS.map((tab) => tab.id));
const scenarioIds = new Set<ScenarioId>(SCENARIO_IDS);

const integerFormatter = new Intl.NumberFormat("ru-RU", {
  maximumFractionDigits: 0,
});
const decimalFormatter = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});
const percentFormatter = new Intl.NumberFormat("ru-RU", {
  style: "percent",
  maximumFractionDigits: 1,
});
const dateFormatter = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "long",
  year: "numeric",
});
const dateTimeFormatter = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "long",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function isResultTabId(value: string | null | undefined): value is ResultTabId {
  return value !== null && value !== undefined && resultTabIds.has(value as ResultTabId);
}

export function resultTabFromSearch(value: string | null | undefined): ResultTabId {
  return isResultTabId(value) ? value : DEFAULT_RESULT_TAB;
}

export function isScenarioId(value: string | null | undefined): value is ScenarioId {
  return value !== null && value !== undefined && scenarioIds.has(value as ScenarioId);
}

export function fixedScenarioLabel(scenario: Pick<Scenario, "scenario_id" | "title">): string {
  return SCENARIO_PRESENTATION[scenario.scenario_id].fixedLabel ?? scenario.title;
}

export function scenarioShortLabel(scenarioId: ScenarioId): string {
  return SCENARIO_PRESENTATION[scenarioId].shortLabel;
}

export function dedupeScenarioIds(
  scenarioIdsToShow: readonly (ScenarioId | null | undefined)[],
): ScenarioId[] {
  const seen = new Set<ScenarioId>();
  const result: ScenarioId[] = [];
  for (const scenarioId of scenarioIdsToShow) {
    if (scenarioId === null || scenarioId === undefined || seen.has(scenarioId)) continue;
    seen.add(scenarioId);
    result.push(scenarioId);
  }
  return result;
}

/**
 * Returns the mandatory overview comparison in product order. Recommendation is
 * already selected by the backend; this helper only removes duplicate cards.
 */
export function overviewScenarioIds(view: JobResultViewV1): ScenarioId[] {
  return dedupeScenarioIds([
    view.overview.source_scenario_id,
    view.overview.benchmark_scenario_id,
    view.recommendation.status === "recommended" ? view.recommendation.scenario_id : null,
  ]);
}

function isCompletedMediaPlanOption(view: JobResultViewV1, scenarioId: ScenarioId): boolean {
  return view.media_plan.scenario_options.some(
    (option) => option.scenario_id === scenarioId && option.status === "completed",
  );
}

/**
 * Chooses only which already-calculated media plan is displayed. It never
 * changes recommendation, safe/raw ranks or scenario data.
 */
export function defaultMediaPlanScenarioId(view: JobResultViewV1): ScenarioId | null {
  const recommendation =
    view.recommendation.status === "recommended" ? view.recommendation.scenario_id : null;
  if (recommendation && isCompletedMediaPlanOption(view, recommendation)) return recommendation;
  if (isCompletedMediaPlanOption(view, "S05")) return "S05";
  if (isCompletedMediaPlanOption(view, "S01")) return "S01";
  return null;
}

export function mediaPlanScenarioFromSearch(
  view: JobResultViewV1,
  requestedScenario: string | null | undefined,
): ScenarioId | null {
  if (isScenarioId(requestedScenario) && isCompletedMediaPlanOption(view, requestedScenario)) {
    return requestedScenario;
  }
  return defaultMediaPlanScenarioId(view);
}

/** Builds URL state only. Scenario is a view selector, not a recommendation mutation. */
export function resultSearchParams(
  tab: ResultTabId,
  scenarioId?: ScenarioId | null,
): URLSearchParams {
  const params = new URLSearchParams({ tab });
  if (tab === "media-plan" && scenarioId !== null && scenarioId !== undefined) {
    params.set("scenario", scenarioId);
  }
  return params;
}

export function scenarioById(view: JobResultViewV1, scenarioId: ScenarioId): Scenario {
  return view.scenarios.find((scenario) => scenario.scenario_id === scenarioId) ?? view.scenarios[0];
}

export function metricDefinition(metricId: ScenarioMetricId): ScenarioMetricDefinition {
  return SCENARIO_METRICS.find((metric) => metric.id === metricId) ?? SCENARIO_METRICS[0];
}

export function metricForScenario(
  scenario: Scenario,
  metricId: ScenarioMetricId,
): QuantileMetric {
  return scenario.metrics[metricId];
}

export function formatMetricValue(value: number | null, unit: MetricUnit): string {
  if (value === null || !Number.isFinite(value)) return "Нет данных";
  switch (unit) {
    case "RUB":
    case "turnover_bridge_from_avg_basket_rub":
      return `${integerFormatter.format(value)} ₽`;
    case "RUB_per_order":
      return `${decimalFormatter.format(value)} ₽/заказ`;
    case "orders":
      return integerFormatter.format(value);
    case "orders_per_100k_RUB":
      return `${decimalFormatter.format(value)} на 100 000 ₽`;
    case "ratio":
      return decimalFormatter.format(value);
  }
}

export function formatMetricRange(metric: QuantileMetric): string {
  if (
    metric.status !== "available" ||
    metric.p10 === null ||
    metric.p50 === null ||
    metric.p90 === null
  ) {
    return "Нет данных";
  }
  return `${formatMetricValue(metric.p50, metric.unit)} · P10–P90: ${formatMetricValue(metric.p10, metric.unit)} — ${formatMetricValue(metric.p90, metric.unit)}`;
}

export function formatRub(value: number | null): string {
  return formatMetricValue(value, "RUB");
}

export function formatPercent(value: number | null): string {
  return value === null || !Number.isFinite(value) ? "Нет данных" : percentFormatter.format(value);
}

export function formatRank(value: number | null): string {
  return value === null ? "Нет данных" : `№ ${integerFormatter.format(value)}`;
}

export function formatDate(value: string | null): string {
  if (value === null) return "Нет данных";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : dateFormatter.format(date);
}

export function formatDateTime(value: string | null): string {
  if (value === null) return "Нет данных";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : dateTimeFormatter.format(date);
}

export function isPartialCoverage(view: JobResultViewV1): boolean {
  return view.campaign.model_coverage_share < 1;
}

export function recommendationScenario(view: JobResultViewV1): Scenario | null {
  if (view.recommendation.status !== "recommended" || view.recommendation.scenario_id === null) {
    return null;
  }
  return scenarioById(view, view.recommendation.scenario_id);
}
