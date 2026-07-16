import type {
  QuantileMetric,
  QualityStatus,
  ReliabilityComponent,
  Scenario,
  ScenarioId,
} from "../../shared/api/generated/job-result-view-v1";
import {
  formatDate,
  formatDecimal,
  formatInteger,
  formatPercent,
  formatRub,
  formatSignedRub,
} from "../../shared/formatters/metrics";

export type ResultTone = "neutral" | "accent" | "warning" | "danger";

export const RESULT_METRICS = [
  { id: "incremental_turnover_rub", label: "Дополнительный оборот" },
  { id: "roas", label: "ROAS по обороту" },
  { id: "incremental_orders", label: "Дополнительные заказы" },
  { id: "orders_per_100k_rub", label: "Заказы на 100 000 ₽" },
  { id: "avg_basket_turnover_bridge_rub", label: "Вклад механизма среднего чека" },
] as const;

export type ResultMetricId = (typeof RESULT_METRICS)[number]["id"];

export function scenarioNumber(id: ScenarioId): string {
  return String(Number(id.slice(1)));
}

export function scenarioAnchorLabel(id: ScenarioId): string | null {
  if (id === "S01") return "Исходный план";
  if (id === "S05") return "Устойчивый ориентир";
  return null;
}

export function scenarioDisplayName(scenario: Scenario): string {
  if (scenario.scenario_id === "S01") return "Как загружено";
  if (scenario.scenario_id === "S05") return "Устойчивый ориентир";
  return scenario.title;
}

export function qualityLabel(status: QualityStatus): string {
  return {
    safe: "Можно использовать",
    caution: "Использовать осторожно",
    blocked: "Требуется ручная проверка",
    unavailable: "Нет данных",
  }[status];
}

export function qualityTone(status: QualityStatus): ResultTone {
  if (status === "safe") return "accent";
  if (status === "caution") return "warning";
  if (status === "blocked") return "danger";
  return "neutral";
}

export function reliabilityTone(
  status: ReliabilityComponent["status"],
): ResultTone {
  if (status === "good") return "accent";
  if (status === "caution") return "warning";
  if (status === "poor") return "danger";
  return "neutral";
}

export function metricValue(metric: QuantileMetric, value: number | null): string {
  if (metric.status === "unavailable" || value === null) return "Нет данных";
  if (
    metric.unit === "RUB" ||
    metric.unit === "RUB_per_order" ||
    metric.unit === "turnover_bridge_from_avg_basket_rub"
  ) {
    return formatRub(value);
  }
  if (metric.unit === "orders") return formatInteger(value);
  return formatDecimal(value);
}

export function metricRange(metric: QuantileMetric): string {
  if (
    metric.status === "unavailable" ||
    metric.p10 === null ||
    metric.p50 === null ||
    metric.p90 === null
  ) {
    return "Нет данных";
  }
  return `${metricValue(metric, metric.p10)} — ${metricValue(metric, metric.p90)}`;
}

export function metricUsageLabel(metric: QuantileMetric): string | null {
  if (metric.usage === "diagnostic_only") return "Диагностический показатель";
  if (metric.usage === "audit_only") return "Только для проверки расчета";
  return null;
}

export function formatGeneratedAt(value: string | null): string {
  if (value === null) return "Время формирования не указано";
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.valueOf())) return "Время формирования не указано";
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

export function campaignPeriod(start: string, end: string): string {
  return `${formatDate(start)} — ${formatDate(end)}`;
}

export function formatCoverage(value: number): string {
  return formatPercent(value);
}

export function formatBudgetDelta(value: number): string {
  return formatSignedRub(value);
}

export function formatDeltaPercent(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "Нет данных";
  if (value === 0) return "0 %";
  return `${value > 0 ? "+" : "−"}${formatDecimal(Math.abs(value))} %`;
}

export function metricForScenario(
  scenario: Scenario,
  metricId: ResultMetricId,
): QuantileMetric {
  return scenario.metrics[metricId];
}
