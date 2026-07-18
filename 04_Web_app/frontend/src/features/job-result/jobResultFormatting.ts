import type {
  Quantiles,
  Scenario,
} from "../../shared/api/generated/job-result-view-v2";
import { formatDate, formatDecimal, formatPercent, formatRub } from "../../shared/formatters/metrics";

export type ResultTone = "neutral" | "accent" | "warning" | "danger";

export function scenarioNumber(id: Scenario["scenario_id"]): string {
  return String(Number(id.slice(1)));
}

export function scenarioDisplayName(scenario: Scenario): string {
  if (scenario.scenario_id === "S01") return "Исходный план";
  if (scenario.scenario_id === "S05") {
    return scenarioVariantTitle(scenario) ?? "Осторожный план";
  }
  if (scenario.scenario_id === "S06") return "План максимального эффекта";
  return scenario.name;
}

export function scenarioVariantTitle(scenario: Scenario): string | null {
  if (scenario.scenario_id !== "S05") return null;
  if (scenario.scenario_variant === "full_conservative") return "Полный осторожный план";
  if (scenario.scenario_variant === "safe_partial") return "Безопасно распределяемая часть";
  return null;
}

export function scenarioAnchorLabel(scenario: Scenario): string | null {
  if (scenario.scenario_id === "S01") return "Точка отсчета";
  if (scenario.scenario_id === "S05" && scenario.scenario_variant === "full_conservative") {
    return "Весь бюджет распределен";
  }
  if (scenario.scenario_id === "S05" && scenario.scenario_variant === "safe_partial") {
    return "Распределена безопасная часть";
  }
  return null;
}

export function decisionLabel(status: Scenario["decision_status"]): string {
  return {
    recommended_reallocation: "Рекомендованное перераспределение",
    keep_uploaded_plan: "Сохранить исходный план",
    manual_review_required: "Требуется ручная проверка",
    no_safe_recommendation: "Безопасная рекомендация не найдена",
    unavailable: "Рекомендация недоступна",
  }[status];
}

export function decisionTone(status: Scenario["decision_status"]): ResultTone {
  if (status === "recommended_reallocation") return "accent";
  if (["manual_review_required", "no_safe_recommendation", "keep_uploaded_plan"].includes(status)) {
    return "warning";
  }
  return "neutral";
}

export function reviewLabel(status: Scenario["review_status"]): string {
  return status === "manual_review_required" ? "Требуется ручная проверка" : "Дополнительная проверка не требуется";
}

export function reliabilityLabel(status: Scenario["reliability"]["status"]): string {
  return {
    within_support: "Внутри надежного диапазона",
    controlled_extrapolation: "Контролируемое расширение",
    high_risk: "Высокий риск",
    manual_review: "Требуется ручная проверка",
    unavailable: "Нет данных",
  }[status];
}

export function reliabilityTone(status: Scenario["reliability"]["status"]): ResultTone {
  if (status === "within_support") return "accent";
  if (status === "controlled_extrapolation" || status === "manual_review") return "warning";
  if (status === "high_risk") return "danger";
  return "neutral";
}

export function quantileValue(metric: Quantiles, value: number | null): string {
  if (metric.status !== "available" || value === null) return "Нет данных";
  return metric.unit === "RUB" ? formatRub(value) : formatDecimal(value);
}

export function quantileRange(metric: Quantiles): string {
  if (metric.status !== "available" || metric.p10 === null || metric.p90 === null) return "Нет данных";
  return `${quantileValue(metric, metric.p10)} — ${quantileValue(metric, metric.p90)}`;
}

export function budgetAllocationLabel(scenario: Scenario): string {
  return `${formatRub(scenario.budget.allocated_budget_rub)} из ${formatRub(scenario.budget.requested_budget_rub)}`;
}

export function allocationShareLabel(scenario: Scenario): string {
  return formatPercent(scenario.budget.allocation_share);
}

export function scenarioStatusLabel(scenario: Scenario): string {
  if (scenario.status === "infeasible") return "Полный план недоступен";
  if (scenario.status === "unavailable") return "Нет данных";
  return "Рассчитан";
}

export function campaignPeriod(start: string, end: string): string {
  return `${formatDate(start)} — ${formatDate(end)}`;
}
