import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { JobProgressViewV1 } from "../../shared/api/generated/job-progress-view-v1";
import {
  JobProgressInconsistentError,
  JobProgressNotFoundError,
  JobProgressRequestError,
  UnsupportedJobProgressContractError,
} from "../../shared/api/job-progress-client";
import { JobProgressPage } from "../../pages/JobProgressPage";

const apiMocks = vi.hoisted(() => ({
  progress: vi.fn(),
  facts: vi.fn(),
  cancel: vi.fn(),
}));

vi.mock("../../shared/api/job-progress-client", async () => {
  const actual = await vi.importActual<typeof import("../../shared/api/job-progress-client")>(
    "../../shared/api/job-progress-client",
  );
  return {
    ...actual,
    getJobProgressView: apiMocks.progress,
    getMmmFacts: apiMocks.facts,
  };
});

vi.mock("../../shared/api/lifecycle-client", async () => {
  const actual = await vi.importActual<typeof import("../../shared/api/lifecycle-client")>(
    "../../shared/api/lifecycle-client",
  );
  return { ...actual, cancelJob: apiMocks.cancel };
});

const JOB_ID = "job_000000000001";

function snapshot(status: "running" | "succeeded" = "running"): JobProgressViewV1 {
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
  const terminal = status === "succeeded";
  return {
    contract_name: "job_progress_view_v1",
    schema_version: "1.0.0",
    record_origin: "synthetic_fixture",
    job_id: JOB_ID,
    job_status: { code: status, display_text: status },
    queue: { position: null, queued_jobs_total: 0, display_text: "Расчет уже запущен." },
    campaign: {
      campaign_id: "campaign_000000000002",
      campaign_name: "Синтетический orchestration test",
      segment: ["Сегмент"],
      start_date: "2026-08-01",
      end_date: "2026-08-31",
      total_budget_rub: 100,
      channels_n: 1,
      geographies_n: 1,
    },
    current_stage_id: terminal ? "P09" : "P02",
    stages: titles.map((title, index) => ({
      stage_id: `P${String(index + 1).padStart(2, "0")}` as JobProgressViewV1["current_stage_id"],
      order: index + 1,
      title,
      status: terminal ? "completed" as const : index === 0 ? "completed" as const : index === 1 ? "active" as const : "pending" as const,
      started_at_utc: terminal || index <= 1 ? `2026-07-16T10:0${index}:00Z` : null,
      finished_at_utc: terminal || index === 0 ? `2026-07-16T10:0${index}:30Z` : null,
      display_text: `${title}.`,
      progress: null,
    })) as JobProgressViewV1["stages"],
    scenario6: {
      status: terminal ? "completed" : "pending",
      attempt_budget: null,
      attempts_checked: null,
      safe_candidates: null,
      blocked_candidates: null,
      finalists_scored: null,
      finalists_total: null,
    },
    report: {
      status: terminal ? "completed" : "pending",
      display_text: terminal ? "Excel-отчет готов." : "Отчет ожидает.",
      retryable: false,
    },
    errors: [],
    can_cancel: !terminal,
    result_available: terminal,
    updated_at_utc: "2026-07-16T10:20:00Z",
  };
}

function LocationProbe() {
  return <output data-testid="route">{useLocation().pathname}</output>;
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/calculations/${JOB_ID}/progress`]}>
        <Routes>
          <Route
            path="/calculations/:id/progress"
            element={<><JobProgressPage /><LocationProbe /></>}
          />
          <Route path="/calculations/:id/result" element={<div>Результат открыт</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return queryClient;
}

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("JobProgressPage orchestration", () => {
  it("keeps the last successful snapshot when a refresh fails", async () => {
    apiMocks.progress.mockResolvedValueOnce(snapshot("running"));
    apiMocks.facts.mockRejectedValue(new Error("facts unavailable"));
    const queryClient = renderPage();
    expect(await screen.findByRole("heading", { name: "Синтетический orchestration test" })).toBeInTheDocument();

    apiMocks.progress.mockRejectedValueOnce(new JobProgressRequestError());
    await act(async () => {
      await queryClient.refetchQueries({ queryKey: ["job-progress-view", JOB_ID] });
    });

    expect(screen.getByRole("heading", { name: "Синтетический orchestration test" })).toBeInTheDocument();
    expect(await screen.findByText(/Последние полученные сведения сохранены/)).toBeInTheDocument();
  });

  it("stops polling for a terminal snapshot and never redirects automatically", async () => {
    vi.useFakeTimers();
    apiMocks.progress.mockResolvedValue(snapshot("succeeded"));
    apiMocks.facts.mockRejectedValue(new Error("facts unavailable"));
    renderPage();

    await act(async () => {
      await Promise.resolve();
    });
    expect(apiMocks.progress).toHaveBeenCalledOnce();
    await act(async () => {
      vi.advanceTimersByTime(4_000);
      await Promise.resolve();
    });
    expect(apiMocks.progress).toHaveBeenCalledOnce();
    expect(screen.getByTestId("route")).toHaveTextContent(`/calculations/${JOB_ID}/progress`);
    expect(screen.queryByText("Результат открыт")).not.toBeInTheDocument();
  });

  it("does not poll after an initial request fails without a valid snapshot", async () => {
    vi.useFakeTimers();
    apiMocks.progress.mockRejectedValue(new JobProgressRequestError());
    apiMocks.facts.mockRejectedValue(new Error("facts unavailable"));
    renderPage();

    await act(async () => {
      await Promise.resolve();
    });
    expect(apiMocks.progress).toHaveBeenCalledOnce();
    await act(async () => {
      vi.advanceTimersByTime(4_000);
      await Promise.resolve();
    });
    expect(apiMocks.progress).toHaveBeenCalledOnce();
  });

  it.each([
    [new JobProgressNotFoundError(), "Расчет не найден", null],
    [new JobProgressInconsistentError(), "Состояние расчета временно не согласовано", "Обновить сведения"],
    [new UnsupportedJobProgressContractError(), "Формат сведений не поддерживается", "Повторить"],
  ] as const)("renders a controlled initial state", async (error, title, action) => {
    apiMocks.progress.mockRejectedValue(error);
    apiMocks.facts.mockRejectedValue(new Error("facts unavailable"));
    renderPage();
    expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
    if (action) expect(screen.getByRole("button", { name: action })).toBeInTheDocument();
  });

  it("keeps the page usable when facts are unavailable", async () => {
    apiMocks.progress.mockResolvedValue(snapshot("running"));
    apiMocks.facts.mockRejectedValue(new Error("facts unavailable"));
    renderPage();
    expect(await screen.findByRole("heading", { name: "Этапы расчета" })).toBeInTheDocument();
    await waitFor(() => expect(apiMocks.facts).toHaveBeenCalledOnce());
    expect(screen.queryByRole("heading", { name: "MMM за минуту" })).not.toBeInTheDocument();
  });
});
