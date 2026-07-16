import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { JobProgressViewV1 } from "../../shared/api/generated/job-progress-view-v1";
import { JobProgressView } from "./JobProgressView";

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

function view(status: JobProgressViewV1["job_status"]["code"] = "running"): JobProgressViewV1 {
  const terminal = ["succeeded", "failed", "cancelled", "timed_out"].includes(status);
  const currentIndex = status === "queued" ? 0 : status === "succeeded" ? 8 : 5;
  const stages = titles.map((title, index) => {
    const completed = status === "succeeded" || index < currentIndex;
    const active = !terminal && index === currentIndex;
    return {
      stage_id: `P${String(index + 1).padStart(2, "0")}` as JobProgressViewV1["current_stage_id"],
      order: index + 1,
      title,
      status: completed ? "completed" as const : active ? "active" as const : terminal ? "skipped" as const : "pending" as const,
      started_at_utc: completed || active ? `2026-07-16T10:${String(index).padStart(2, "0")}:00Z` : null,
      finished_at_utc: completed ? `2026-07-16T10:${String(index).padStart(2, "0")}:30Z` : null,
      display_text: `${title}: понятное описание этапа.`,
      progress: active ? { current: 1_536, total: 2_048, unit: "вариантов" } : null,
    };
  }) as JobProgressViewV1["stages"];
  return {
    contract_name: "job_progress_view_v1",
    schema_version: "1.0.0",
    record_origin: "synthetic_fixture",
    job_id: "job_000000000001",
    job_status: { code: status, display_text: "Синтетический статус" },
    queue: {
      position: status === "queued" ? 2 : null,
      queued_jobs_total: status === "queued" ? 5 : 0,
      display_text: "Расчет ожидает свободного места.",
    },
    campaign: {
      campaign_id: "campaign_000000000002",
      campaign_name: "Очень длинное синтетическое название кампании для проверки переноса строк",
      segment: ["Синтетический сегмент A", "Синтетический сегмент Б"],
      start_date: "2026-08-01",
      end_date: "2026-08-31",
      total_budget_rub: 12_000_000,
      channels_n: 4,
      geographies_n: 12,
    },
    current_stage_id: stages[currentIndex].stage_id,
    stages,
    scenario6: {
      status: status === "succeeded" ? "completed" : "running",
      attempt_budget: 2_048,
      attempts_checked: 1_536,
      safe_candidates: 0,
      blocked_candidates: null,
      finalists_scored: 11,
      finalists_total: 600,
    },
    report: {
      status: status === "succeeded" ? "completed" : "pending",
      display_text: status === "succeeded" ? "Excel-отчет готов." : "Отчет ожидает проверки.",
      retryable: false,
    },
    errors: [],
    can_cancel: status === "queued" || status === "running",
    result_available: status === "succeeded",
    updated_at_utc: "2026-07-16T10:20:00Z",
  };
}

function LocationProbe() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}

interface RenderViewOptions {
  onCancel?: () => Promise<void>;
  cancelPending?: boolean;
  cancelError?: string | null;
  fact?: { fact_id: string; category: "forecast"; text: string; source_label: string } | null;
}

function progressViewTree(
  progressView: JobProgressViewV1,
  options: RenderViewOptions = {},
) {
  return (
    <MemoryRouter initialEntries={[`/calculations/${progressView.job_id}/progress`]}>
      <JobProgressView
        view={progressView}
        fact={options.fact ?? null}
        onRefresh={() => undefined}
        onCancel={options.onCancel ?? vi.fn().mockResolvedValue(undefined)}
        cancelPending={options.cancelPending ?? false}
        cancelError={options.cancelError ?? null}
      />
      <LocationProbe />
    </MemoryRouter>
  );
}

function renderView(
  progressView: JobProgressViewV1,
  options: RenderViewOptions = {},
) {
  return render(progressViewTree(progressView, options));
}

afterEach(() => {
  vi.useRealTimers();
});

describe("JobProgressView", () => {
  it("shows campaign context, fixed stages and known queue position", () => {
    renderView(view("queued"));
    expect(screen.getByRole("heading", { name: /Очень длинное синтетическое/ })).toBeInTheDocument();
    expect(screen.getByText("Позиция в очереди: 2 из 5")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(9);
    expect(screen.getByText("Демонстрационные данные")).toBeInTheDocument();
  });

  it("shows an unknown queue position without converting null to zero", () => {
    const payload = view("queued");
    payload.queue.position = null;
    payload.queue.queued_jobs_total = 0;
    renderView(payload);
    expect(screen.getByText("Положение в очереди уточняется")).toBeInTheDocument();
    expect(screen.queryByText(/Позиция в очереди: 0/)).not.toBeInTheDocument();
  });

  it("renders only real Scenario 6 counters and hides zero safe count", () => {
    renderView(view("running"));
    expect(screen.getByText("Проверено вариантов").parentElement).toHaveTextContent(
      "1 536 / 2 048",
    );
    expect(screen.getByText("Пересчитано финалистов").parentElement).toHaveTextContent(
      "11 / 600",
    );
    expect(screen.queryByText("Прошли проверку")).not.toBeInTheDocument();
    expect(screen.queryByText("нет безопасных вариантов", { exact: false })).not.toBeInTheDocument();
  });

  it("keeps available Scenario 6 current counters when totals are absent", () => {
    const payload = view("running");
    payload.scenario6.attempts_checked = 17;
    payload.scenario6.attempt_budget = null;
    payload.scenario6.finalists_scored = 3;
    payload.scenario6.finalists_total = null;
    renderView(payload);

    expect(screen.getByText("Проверено вариантов").parentElement).toHaveTextContent("17");
    expect(screen.getByText("Пересчитано финалистов").parentElement).toHaveTextContent("3");
    expect(screen.queryByText(/17\s*\//)).not.toBeInTheDocument();
    expect(screen.queryByText(/3\s*\//)).not.toBeInTheDocument();
  });

  it("keeps success on the progress page and exposes result only as a link", () => {
    vi.useFakeTimers();
    renderView(view("succeeded"));
    expect(screen.getByRole("link", { name: "Открыть результат" })).toHaveAttribute(
      "href",
      "/calculations/job_000000000001/result",
    );
    vi.advanceTimersByTime(1_500);
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/calculations/job_000000000001/progress",
    );
  });

  it.each([
    ["failed", "Расчет завершился с ошибкой"],
    ["cancelled", "Расчет отменен"],
    ["timed_out", "Расчет не завершен вовремя"],
    ["cancel_requested", "Расчет останавливается"],
  ] as const)("renders the %s product state", (status, title) => {
    const payload = view(status);
    payload.can_cancel = false;
    renderView(payload);
    expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Открыть результат" })).not.toBeInTheDocument();
  });

  it("opens a keyboard-safe cancel dialog and waits for confirmation", async () => {
    const onCancel = vi.fn().mockResolvedValue(undefined);
    renderView(view("running"), { onCancel });
    const trigger = screen.getByRole("button", { name: "Отменить расчет" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Отменить расчет?" });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Продолжить расчет" })).toHaveFocus();
    fireEvent.click(screen.getAllByRole("button", { name: "Отменить расчет" })[1]);
    await waitFor(() => expect(onCancel).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("closes the cancel dialog with Escape and keeps calculation running", () => {
    const onCancel = vi.fn().mockResolvedValue(undefined);
    renderView(view("running"), { onCancel });
    fireEvent.click(screen.getByRole("button", { name: "Отменить расчет" }));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("keeps focus trapped while cancellation is pending", async () => {
    const payload = view("running");
    const rendered = renderView(payload);
    fireEvent.click(screen.getByRole("button", { name: "Отменить расчет" }));
    const dialog = screen.getByRole("dialog", { name: "Отменить расчет?" });

    rendered.rerender(progressViewTree(payload, { cancelPending: true }));
    await waitFor(() => expect(dialog).toHaveFocus());
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(dialog).toHaveFocus();
  });

  it("closes cancellation safely when a refreshed snapshot disallows it", async () => {
    const rendered = renderView(view("running"));
    fireEvent.click(screen.getByRole("button", { name: "Отменить расчет" }));
    expect(screen.getByRole("dialog", { name: "Отменить расчет?" })).toBeInTheDocument();

    const refreshed = view("cancel_requested");
    refreshed.can_cancel = false;
    rendered.rerender(progressViewTree(refreshed));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Расчет останавливается" })).toHaveFocus();
    });
  });

  it("orders blocking errors first and exposes only safe guidance", () => {
    const payload = view("failed");
    payload.errors = [
      {
        error_id: "error_000000000001",
        stage_id: "P06",
        severity: "warning",
        blocking: false,
        retryable: false,
        display_text: "Сначала предупреждение",
        recommended_action: "Проверить план",
      },
      {
        error_id: "error_000000000002",
        stage_id: "P02",
        severity: "error",
        blocking: true,
        retryable: true,
        display_text: "Блокирующая ошибка",
        recommended_action: "Исправить исходный файл",
      },
      {
        error_id: "error_000000000003",
        stage_id: "P03",
        severity: "error",
        blocking: false,
        retryable: false,
        display_text: "Предыдущая неблокирующая ошибка",
        recommended_action: "Проверить историю запуска",
      },
    ];
    renderView(payload);
    const cards = screen.getByRole("heading", { name: "Замечания по расчету" })
      .closest("section")?.querySelectorAll("li");
    expect(cards?.[0]).toHaveTextContent("Блокирующая ошибка");
    expect(screen.getByText("Предыдущая неблокирующая ошибка").closest("li")).toHaveTextContent(
      "Ошибка",
    );
    expect(screen.queryByText(/error_000000000002/)).not.toBeInTheDocument();
  });

  it("shows one optional fact and hides its machine category", () => {
    renderView(view("running"), {
      fact: {
        fact_id: "fact_synthetic_01",
        category: "forecast",
        text: "Диапазон показывает неопределенность оценки.",
        source_label: "Методическая памятка",
      },
    });
    expect(screen.getByRole("heading", { name: "MMM за минуту" })).toBeInTheDocument();
    expect(screen.getByText("Источник: Методическая памятка")).toBeInTheDocument();
    expect(screen.queryByText("forecast")).not.toBeInTheDocument();
  });

  it("does not render raw implementation terms", () => {
    renderView(view("running"));
    const text = document.body.textContent ?? "";
    for (const rawTerm of ["Progress events", "candidate_id", "attempt_id", "posterior"]) {
      expect(text).not.toContain(rawTerm);
    }
  });
});
