import { describe, expect, it } from "vitest";
import type { JobProgressViewV1 } from "../../shared/api/generated/job-progress-view-v1";
import type { MMMFactCatalogV1 } from "../../shared/api/generated/mmm-fact-catalog-v1";
import {
  currentStatusCopy,
  formatCounterPair,
  isTerminalJobStatus,
  jobStatusLabel,
  queuePositionText,
  scenario6StatusText,
  selectFactForJob,
  sortProgressErrors,
  stageStatusLabel,
} from "./jobProgressModel";

function minimalView(): JobProgressViewV1 {
  const titles = [
    "Расчет ожидает запуска",
    "Подготавливаем медиаплан",
    "Рассчитываем исходный медиаплан",
    "Рассчитываем контрольные сценарии",
    "Ищем устойчивый вариант",
    "Перебираем варианты распределения",
    "Проверяем результаты",
    "Формируем отчет",
    "Расчет завершен",
  ];
  return {
    contract_name: "job_progress_view_v1",
    schema_version: "1.0.0",
    record_origin: "synthetic_fixture",
    job_id: "job_000000000001",
    job_status: { code: "running", display_text: "Расчет выполняется" },
    queue: { position: null, queued_jobs_total: null, display_text: "Расчет уже запущен." },
    campaign: {
      campaign_id: "campaign_000000000002",
      campaign_name: "Синтетическая кампания",
      segment: ["Сегмент"],
      start_date: "2026-08-01",
      end_date: "2026-08-31",
      total_budget_rub: 1,
      channels_n: 1,
      geographies_n: 1,
    },
    current_stage_id: "P02",
    stages: titles.map((title, index) => ({
      stage_id: `P${String(index + 1).padStart(2, "0")}` as JobProgressViewV1["current_stage_id"],
      order: index + 1,
      title,
      status: index === 1 ? "active" as const : "pending" as const,
      started_at_utc: index === 1 ? "2026-07-16T10:00:00Z" : null,
      finished_at_utc: null,
      display_text: `${title}.`,
      progress: null,
    })) as JobProgressViewV1["stages"],
    scenario6: {
      status: "pending",
      attempt_budget: null,
      attempts_checked: null,
      safe_candidates: null,
      blocked_candidates: null,
      finalists_scored: null,
      finalists_total: null,
    },
    report: { status: "pending", display_text: "Отчет ожидает.", retryable: false },
    errors: [],
    can_cancel: true,
    result_available: false,
    updated_at_utc: "2026-07-16T10:01:00Z",
  };
}

describe("job progress presentation", () => {
  it.each([
    ["queued", "В очереди"],
    ["running", "Выполняется"],
    ["cancel_requested", "Останавливается"],
    ["succeeded", "Готово"],
    ["failed", "Ошибка"],
    ["cancelled", "Отменено"],
    ["timed_out", "Не завершено вовремя"],
  ] as const)("maps %s to marketer copy", (status, label) => {
    expect(jobStatusLabel(status)).toBe(label);
  });

  it("uses the backend-selected stage without deriving another stage", () => {
    const view = minimalView();
    expect(currentStatusCopy(view)).toEqual({
      title: "Подготавливаем медиаплан",
      description: "Подготавливаем медиаплан.",
    });
  });

  it("keeps unknown queue position distinct from a known position", () => {
    const view = minimalView();
    view.job_status.code = "queued";
    expect(queuePositionText(view)).toBe("Положение в очереди уточняется");
    view.queue.position = 1;
    view.queue.queued_jobs_total = 4;
    expect(queuePositionText(view)).toBe("Позиция в очереди: 1 из 4");
  });

  it("formats real counters without converting them to percentages", () => {
    expect(formatCounterPair(1_536, 2_048)).toBe("1 536 / 2 048");
  });

  it.each([
    ["pending", "Поиск вариантов еще не начался"],
    ["running", "Идет проверка вариантов распределения"],
    ["completed", "Поиск вариантов завершен"],
    ["unavailable", "Адаптивный поиск не применялся"],
    ["failed", "Не удалось завершить поиск вариантов"],
  ] as const)("maps Scenario 6 %s independently", (status, label) => {
    expect(scenario6StatusText(status)).toBe(label);
  });

  it("distinguishes stage warning, failure and skipped", () => {
    expect(stageStatusLabel("warning")).toBe("Завершен с замечанием");
    expect(stageStatusLabel("failed")).toBe("Ошибка");
    expect(stageStatusLabel("skipped")).toBe("Не выполнялся");
  });

  it("recognizes only actual terminal job states", () => {
    expect(isTerminalJobStatus("succeeded")).toBe(true);
    expect(isTerminalJobStatus("cancelled")).toBe(true);
    expect(isTerminalJobStatus("running")).toBe(false);
    expect(isTerminalJobStatus("cancel_requested")).toBe(false);
  });

  it("orders blocking errors above warnings without using error identifiers", () => {
    const errors: JobProgressViewV1["errors"] = [
      {
        error_id: "error_000000000001",
        stage_id: "P06",
        severity: "warning",
        blocking: false,
        retryable: false,
        display_text: "Предупреждение",
        recommended_action: "Проверить",
      },
      {
        error_id: "error_000000000002",
        stage_id: "P02",
        severity: "error",
        blocking: true,
        retryable: true,
        display_text: "Ошибка",
        recommended_action: "Исправить",
      },
    ];
    expect(sortProgressErrors(errors).map((error) => error.display_text)).toEqual([
      "Ошибка",
      "Предупреждение",
    ]);
  });

  it("selects the same fact for the same job without random rotation", () => {
    const catalog = {
      contract_name: "mmm_fact_catalog_v1",
      schema_version: "1.0.0",
      facts: Array.from({ length: 20 }, (_, index) => ({
        fact_id: `fact_synthetic_${String(index).padStart(2, "0")}`,
        category: "forecast" as const,
        text: `Факт ${index}`,
        source_label: "Источник",
      })),
    } as unknown as MMMFactCatalogV1;
    const first = selectFactForJob(catalog, "job_000000000001");
    const second = selectFactForJob(catalog, "job_000000000001");
    expect(first).toEqual(second);
    expect(selectFactForJob(undefined, "job_000000000001")).toBeNull();
  });
});
