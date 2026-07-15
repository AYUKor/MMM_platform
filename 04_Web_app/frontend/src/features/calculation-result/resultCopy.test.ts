import { describe, expect, it } from "vitest";
import {
  getAllocationActionCopy,
  getGateReasonCopy,
  getQualityCopy,
  getScenarioCopy,
  getStatusCopy,
  getWarningCopy,
  getWarningSeverityCopy,
  type ResultStatusDomain,
} from "./resultCopy";

describe("resultCopy", () => {
  it.each<[ResultStatusDomain, string, string]>([
    ["calculation", "calculated", "Расчет готов"],
    ["campaignScale", "above_historical_robust_upper", "Масштаб вне надежной зоны"],
    ["cellSupport", "above_robust_upper", "Есть связки вне надежной зоны"],
    ["optimizer", "best_safe_available", "Безопасный вариант найден"],
    ["businessDecision", "allocation_only", "Только рекомендация по распределению"],
    ["quality", "not_for_automatic_reallocation", "Не для автоматического перераспределения"],
    ["recommendationType", "reallocate_for_reliability", "Перераспределить с учетом устойчивости"],
    ["plan", "full_plan_partial_model_coverage", "Полный план, частичное покрытие модели"],
    ["scenario6Run", "completed_no_safe_candidate", "Допустимый вариант не найден"],
  ])("maps %s status %s to browser-safe copy", (domain, code, label) => {
    expect(getStatusCopy(domain, code)).toMatchObject({ label, known: true });
  });

  it("fails closed for an unknown status without echoing its raw code", () => {
    const rawCode = "RAW_BACKEND_STATUS_DO_NOT_SHOW";
    const copy = getStatusCopy("optimizer", rawCode);

    expect(copy).toMatchObject({
      label: "Статус недоступен",
      tone: "danger",
      known: false,
    });
    expect(JSON.stringify(copy)).not.toContain(rawCode);
  });

  it("provides structured warning copy without using backend display text", () => {
    const copy = getWarningCopy("business_hurdle_not_approved");

    expect(copy).toEqual({
      title: "Не настроен бизнес-порог",
      meaning: "Результат сравнивает способы распределения бюджета, но не отвечает, стоит ли запускать кампанию.",
      action: "Решение о запуске примите отдельно с учетом маржи, целей и согласованного бизнес-порога.",
      tone: "warning",
      known: true,
    });
  });

  it("fails closed for an unknown warning without exposing its code", () => {
    const rawCode = "UNKNOWN_WARNING_FROM_BACKEND";
    const copy = getWarningCopy(rawCode);

    expect(copy).toMatchObject({
      title: "Требуется дополнительная проверка",
      tone: "danger",
      known: false,
    });
    expect(Object.values(copy).join(" ")).not.toContain(rawCode);
  });

  it("labels warning severities in plain language", () => {
    expect(getWarningSeverityCopy("manual_review")).toMatchObject({
      label: "Нужна ручная проверка",
      known: true,
    });
    expect(getWarningSeverityCopy("UNKNOWN_SEVERITY")).toMatchObject({
      label: "Статус недоступен",
      known: false,
    });
  });

  it("uses S5 only as a stable benchmark and never calls it the best plan", () => {
    const copy = getScenarioCopy("S05");

    expect(copy).toMatchObject({
      number: "Сценарий 5",
      badge: "Устойчивый benchmark",
      available: true,
      known: true,
    });
    expect(copy.description).toContain("не автоматически лучший план");
  });

  it("returns a controlled unavailable state for S6", () => {
    expect(getScenarioCopy("S06", false)).toEqual({
      number: "Сценарий 6",
      title: "Адаптивный поиск недоступен",
      description: "Безопасный автоматический вариант не сформирован. Проверьте ограничения и предупреждения расчета.",
      badge: "Недоступно",
      available: false,
      known: true,
    });
  });

  it("does not expose an unknown scenario identifier", () => {
    const rawScenario = "S99_INTERNAL";
    const copy = getScenarioCopy(rawScenario);

    expect(copy.known).toBe(false);
    expect(JSON.stringify(copy)).not.toContain(rawScenario);
  });

  it.each([
    ["increase", "Увеличить"],
    ["decrease", "Уменьшить"],
    ["keep", "Без изменения"],
  ])("maps allocation action %s", (action, expectedLabel) => {
    expect(getAllocationActionCopy(action)).toMatchObject({
      label: expectedLabel,
      known: true,
    });
  });

  it("maps known gate reasons and hides unknown raw reasons", () => {
    expect(getGateReasonCopy("FIXED_SATURATION_SHAPE")).toMatchObject({
      label: "Форма отклика зафиксирована",
      known: true,
    });

    const rawReason = "NEW_INTERNAL_GATE_REASON";
    const unknownCopy = getGateReasonCopy(rawReason);
    expect(unknownCopy).toMatchObject({
      label: "Нужна ручная проверка",
      tone: "danger",
      known: false,
    });
    expect(JSON.stringify(unknownCopy)).not.toContain(rawReason);
  });

  it("keeps quality mapping on the quality status domain", () => {
    expect(getQualityCopy("elevated_uncertainty")).toMatchObject({
      label: "Повышенная неопределенность",
      tone: "warning",
      known: true,
    });
  });
});
