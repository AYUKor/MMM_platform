import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResultOverviewPage } from "../../pages/ResultOverviewPage";
import type { ScenarioId } from "../../shared/api/generated/scenario-media-plan-v2";
import {
  buildJobResultViewV2,
  buildScenarioMediaPlanV2,
  TEST_JOB_ID,
} from "../../test/businessSemanticsV2Fixtures";

vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({ can: (permission: string) => permission === "report.download" }),
}));

const API_BASE_URL = "http://127.0.0.1:8765";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}

function productErrorResponse(code: string, status: number): Response {
  return jsonResponse({
    error: {
      code,
      display_text: "Контролируемое тестовое состояние.",
      retryable: code === "RESOURCE_NOT_READY" || status >= 500,
      user_action: "Повторите запрос.",
    },
  }, status);
}

function requestUrl(input: RequestInfo | URL): URL {
  return new URL(input instanceof Request ? input.url : String(input));
}

function buildReportArtifactsPayload(
  result = buildJobResultViewV2(),
  reportOverrides: Record<string, unknown> = {},
) {
  return {
    contract_name: "job_result_view_v1",
    schema_version: "1.0.0",
    job_id: TEST_JOB_ID,
    result_id: result.result_id,
    campaign: {
      campaign_name: "КОНФЛИКТУЮЩАЯ КАМПАНИЯ ИЗ V1",
      total_budget_rub: 1,
    },
    scenarios: [{ scenario_id: "S01", metrics: { incremental_turnover_rub: { p50: 999_999_999_999 } } }],
    report: {
      status: "ready",
      display_text: "Excel-отчет готов.",
      generated_at_utc: "2026-07-18T12:00:00Z",
      artifact: {
        artifact_id: "artifact_1234567890abcdef",
        display_name: "mmm_campaign_result.xlsx",
        media_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes: 65_536,
        sha256: "a".repeat(64),
        download_path: "/api/v1/artifacts/artifact_1234567890abcdef/download",
      },
      sheets: [{ sheet_name: "Итоги", title: "Итоги", description: "Основные результаты." }],
      working_media_plan: {
        status: "unavailable",
        display_text: "Отдельный рабочий медиаплан пока не опубликован.",
        artifact: null,
      },
      ...reportOverrides,
    },
  };
}

function createContractFetch(options: { reportPayload?: unknown } = {}) {
  const result = buildJobResultViewV2();
  const reportPayload = options.reportPayload ?? buildReportArtifactsPayload(result);
  return vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    void _init;
    const url = requestUrl(input);
    if (url.pathname === `/api/v1/jobs/${TEST_JOB_ID}/result-view-v2`) return jsonResponse(result);
    if (url.pathname === `/api/v1/jobs/${TEST_JOB_ID}/result-view`) return jsonResponse(reportPayload);
    if (url.pathname === `/api/v1/jobs/${TEST_JOB_ID}/media-plan-v2`) {
      const scenarioId = (url.searchParams.get("scenario_id") ?? "S01") as ScenarioId;
      return jsonResponse(buildScenarioMediaPlanV2(scenarioId, {
        page: Number(url.searchParams.get("page") ?? 1),
        pageSize: Number(url.searchParams.get("page_size") ?? 25),
        channel: url.searchParams.get("channel"),
        geo: url.searchParams.get("geo"),
      }));
    }
    return jsonResponse({ detail: "unexpected" }, 500);
  });
}

function NavigationProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  return <aside><output data-testid="location">{`${location.pathname}${location.search}`}</output><button onClick={() => navigate(-1)}>Назад по истории</button><button onClick={() => navigate(1)}>Вперед по истории</button></aside>;
}

function renderPage(initialEntry = `/calculations/${TEST_JOB_ID}/result`) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/calculations/:id/result" element={<><ResultOverviewPage /><NavigationProbe /></>} />
          <Route path="/calculations" element={<div>Список расчетов</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return queryClient;
}

afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe("ResultOverviewPage v2 orchestration", () => {
  it("restores a completed media-plan scenario from URL", async () => {
    vi.stubGlobal("fetch", createContractFetch());
    renderPage(`/calculations/${TEST_JOB_ID}/result?tab=media-plan&scenario=S05`);
    expect(await screen.findByRole("heading", { name: "Исходный план → просматриваемый сценарий" })).toBeInTheDocument();
    expect(screen.getByLabelText("Сценарий")).toHaveValue("S05");
    expect(screen.getByTestId("location")).toHaveTextContent("?tab=media-plan&scenario=S05");
  });

  it("short-circuits infeasible S6 to a completed plan without requesting S6", async () => {
    const fetchMock = createContractFetch();
    vi.stubGlobal("fetch", fetchMock);
    renderPage(`/calculations/${TEST_JOB_ID}/result?tab=media-plan&scenario=S06`);
    await screen.findByRole("heading", { name: "Исходный план → просматриваемый сценарий" });
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("?tab=media-plan&scenario=S01"));
    const mediaUrls = fetchMock.mock.calls.map(([input]) => requestUrl(input)).filter((url) => url.pathname.endsWith("media-plan-v2"));
    expect(mediaUrls.every((url) => url.searchParams.get("scenario_id") !== "S06")).toBe(true);
  });

  it("uses browser history to restore result tabs", async () => {
    vi.stubGlobal("fetch", createContractFetch());
    renderPage();
    await screen.findByRole("heading", { name: "Исходный план сохранен для проверки" });
    fireEvent.click(screen.getByRole("tab", { name: "Медиаплан" }));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("?tab=media-plan&scenario=S01"));
    fireEvent.click(screen.getByRole("tab", { name: "Отчет" }));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("?tab=report"));
    fireEvent.click(screen.getByRole("button", { name: "Назад по истории" }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "Медиаплан" })).toHaveAttribute("aria-selected", "true"));
  });

  it("loads only the narrow report transport on the report tab and keeps v2 as KPI source of truth", async () => {
    const fetchMock = createContractFetch();
    vi.stubGlobal("fetch", fetchMock);
    renderPage();

    const result = buildJobResultViewV2();
    await screen.findByRole("heading", { name: result.campaign.campaign_name });
    expect(fetchMock.mock.calls.some(([input]) => requestUrl(input).pathname.endsWith("/result-view"))).toBe(false);

    fireEvent.click(screen.getByRole("tab", { name: "Отчет" }));
    expect(await screen.findByRole("heading", { name: "Отчет готов" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: result.campaign.campaign_name })).toBeInTheDocument();
    expect(screen.queryByText("КОНФЛИКТУЮЩАЯ КАМПАНИЯ ИЗ V1")).not.toBeInTheDocument();
    expect(screen.queryByText("999 999 999 999")).not.toBeInTheDocument();

    const reportCall = fetchMock.mock.calls.find(([input]) => requestUrl(input).pathname.endsWith("/result-view"));
    expect(reportCall).toBeDefined();
    expect(reportCall?.[1]).toMatchObject({ credentials: "include" });
  });

  it("requests only v2 result and media endpoints with credentialed fetch", async () => {
    const fetchMock = createContractFetch();
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    await screen.findByRole("heading", { name: "Исходный план сохранен для проверки" });
    fireEvent.click(screen.getByRole("tab", { name: "Медиаплан" }));
    await screen.findByText("45 строк · 15 географий");
    const urls = fetchMock.mock.calls.map(([input]) => requestUrl(input));
    expect(urls[0].toString()).toBe(`${API_BASE_URL}/api/v1/jobs/${TEST_JOB_ID}/result-view-v2`);
    expect(urls.some((url) => url.pathname.endsWith("/media-plan-v2"))).toBe(true);
    expect(urls.every((url) => url.pathname.endsWith("/result-view-v2") || url.pathname.endsWith("/media-plan-v2"))).toBe(true);
    for (const [, init] of fetchMock.mock.calls) expect(init).toMatchObject({ credentials: "include" });
  });

  it.each([
    [409, "RESULT_VIEW_INCONSISTENT", "Данные временно не согласованы"],
    [503, "RESULT_VIEW_UNAVAILABLE", "Результат временно недоступен"],
  ] as const)("renders controlled initial HTTP %s state", async (status, code, title) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(productErrorResponse(code, status)));
    renderPage();
    expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
  });

  it("distinguishes a not-ready result", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(productErrorResponse("RESOURCE_NOT_READY", 404)));
    renderPage();
    expect(await screen.findByRole("heading", { name: "Результат еще не опубликован" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Открыть ход расчета" })).toHaveAttribute("href", `/calculations/${TEST_JOB_ID}/progress`);
  });

  it("fails closed for malformed v2", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ ...buildJobResultViewV2(), schema_version: "1.0.0" })));
    renderPage();
    expect(await screen.findByRole("heading", { name: "Данные результата имеют неподдерживаемый формат" })).toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  });

  it("keeps the last validated result snapshot when refresh fails", async () => {
    const result = buildJobResultViewV2();
    let requests = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (requestUrl(input).pathname.endsWith("/result-view-v2")) {
        requests += 1;
        if (requests === 1) return jsonResponse(result);
        throw new TypeError("network unavailable");
      }
      return jsonResponse({}, 500);
    }));
    const queryClient = renderPage();
    await screen.findByRole("heading", { name: result.campaign.campaign_name });
    await act(async () => { await queryClient.refetchQueries({ queryKey: ["job-result-view-v2", TEST_JOB_ID] }); });
    expect(screen.getByRole("heading", { name: result.campaign.campaign_name })).toBeInTheDocument();
    expect(await screen.findByText(/Последний полученный снимок сохранен/)).toBeInTheDocument();
  });
});
