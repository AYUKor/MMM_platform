import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResultOverviewPage } from "../../pages/ResultOverviewPage";
import type { JobResultViewV1, ScenarioId } from "../../shared/api/generated/job-result-view-v1";
import {
  createRecommendedJobResultFixture,
  createScenarioMediaPlanFixture,
  JOB_RESULT_FIXTURE_IDS,
} from "../../test/jobResultFixtures";

vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({ can: () => true }),
}));

const API_BASE_URL = "http://127.0.0.1:8765";
const { jobId: JOB_ID } = JOB_RESULT_FIXTURE_IDS;

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function productErrorResponse(code: string, status: number): Response {
  return jsonResponse({
    error: {
      code,
      display_text: "Контролируемое тестовое состояние.",
      retryable: code === "RESOURCE_NOT_READY" || status >= 500,
      user_action: "Повторите запрос или вернитесь к расчету.",
    },
  }, status);
}

function requestUrl(input: RequestInfo | URL): URL {
  if (input instanceof Request) return new URL(input.url);
  return new URL(String(input));
}

function createContractFetch(result: JobResultViewV1 = createRecommendedJobResultFixture()) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = requestUrl(input);
    if (url.pathname === `/api/v1/jobs/${JOB_ID}/result-view`) {
      return jsonResponse(result);
    }
    if (url.pathname === `/api/v1/jobs/${JOB_ID}/media-plan`) {
      const scenarioId = (url.searchParams.get("scenario_id") ?? "S06") as ScenarioId;
      const page = Number(url.searchParams.get("page") ?? 1);
      const pageSize = Number(url.searchParams.get("page_size") ?? 25);
      return jsonResponse(
        createScenarioMediaPlanFixture({
          resultView: result,
          scenarioId,
          page,
          pageSize,
          channel: url.searchParams.get("channel"),
          geo: url.searchParams.get("geo"),
        }),
      );
    }
    return jsonResponse({ detail: "unexpected test endpoint" }, 500);
  });
}

function NavigationProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <aside>
      <output data-testid="location">{`${location.pathname}${location.search}`}</output>
      <button type="button" onClick={() => navigate(-1)}>Назад по истории</button>
      <button type="button" onClick={() => navigate(1)}>Вперед по истории</button>
    </aside>
  );
}

function renderPage(initialEntry = `/calculations/${JOB_ID}/result`) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route
            path="/calculations/:id/result"
            element={<><ResultOverviewPage /><NavigationProbe /></>}
          />
          <Route path="/calculations" element={<div>Список расчетов</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return queryClient;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("ResultOverviewPage Phase C orchestration", () => {
  it("restores the requested tab and scenario from URL on initial load", async () => {
    const fetchMock = createContractFetch();
    vi.stubGlobal("fetch", fetchMock);
    renderPage(`/calculations/${JOB_ID}/result?tab=media-plan&scenario=S05`);

    expect(await screen.findByRole("heading", { name: "Исходный план → просматриваемый сценарий" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /S5.*Устойчивый ориентир/ })).toBeChecked();
    await waitFor(() => expect(screen.getByText("Только просмотр")).toBeInTheDocument());
    expect(screen.getByTestId("location")).toHaveTextContent(
      `/calculations/${JOB_ID}/result?tab=media-plan&scenario=S05`,
    );
  });

  it("uses browser history to restore tab URL state", async () => {
    vi.stubGlobal("fetch", createContractFetch());
    renderPage();
    await screen.findByRole("heading", { name: "Рекомендуемое распределение бюджета" });

    fireEvent.click(screen.getByRole("tab", { name: "Медиаплан" }));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("?tab=media-plan&scenario=S06"));
    fireEvent.click(screen.getByRole("tab", { name: "Отчет" }));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("?tab=report"));

    fireEvent.click(screen.getByRole("button", { name: "Назад по истории" }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "Медиаплан" })).toHaveAttribute("aria-selected", "true"));
    expect(screen.getByTestId("location")).toHaveTextContent("?tab=media-plan&scenario=S06");

    fireEvent.click(screen.getByRole("button", { name: "Вперед по истории" }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "Отчет" })).toHaveAttribute("aria-selected", "true"));
  });

  it("requests only result-view and media-plan with exact public query names", async () => {
    const fetchMock = createContractFetch();
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    await screen.findByRole("heading", { name: "Рекомендуемое распределение бюджета" });
    fireEvent.click(screen.getByRole("tab", { name: "Медиаплан" }));
    await screen.findByText("Рекомендованный вариант");

    const urls = fetchMock.mock.calls.map(([input]) => requestUrl(input));
    expect(urls[0].toString()).toBe(`${API_BASE_URL}/api/v1/jobs/${JOB_ID}/result-view`);
    expect(urls.some((url) => url.toString() ===
      `${API_BASE_URL}/api/v1/jobs/${JOB_ID}/media-plan?scenario_id=S06&page=1&page_size=25`)).toBe(true);
    expect(urls.every((url) => [
      `/api/v1/jobs/${JOB_ID}/result-view`,
      `/api/v1/jobs/${JOB_ID}/media-plan`,
    ].includes(url.pathname))).toBe(true);
    expect(urls.some((url) => /\/(?:overview|progress|lifecycle)$/.test(url.pathname))).toBe(false);
    expect(urls.some((url) => url.pathname === `/api/v1/jobs/${JOB_ID}/result`)).toBe(false);
  });

  it("switches media-plan scenario as view state without changing recommendation", async () => {
    const result = createRecommendedJobResultFixture();
    const fetchMock = createContractFetch(result);
    vi.stubGlobal("fetch", fetchMock);
    renderPage(`/calculations/${JOB_ID}/result?tab=media-plan`);
    await screen.findByText("Рекомендованный вариант");

    fireEvent.click(screen.getByRole("radio", { name: /S1.*Как загружено/ }));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("?tab=media-plan&scenario=S01"));
    await waitFor(() => expect(screen.getByText("Только просмотр")).toBeInTheDocument());
    expect(fetchMock.mock.calls.map(([input]) => requestUrl(input).searchParams.get("scenario_id"))).toContain("S01");

    fireEvent.click(screen.getByRole("tab", { name: "Обзор" }));
    expect((await screen.findAllByText("S6 · Адаптивное распределение")).length).toBeGreaterThan(0);
    expect(screen.getByText("Рекомендован системой")).toBeInTheDocument();
    expect(result.recommendation.scenario_id).toBe("S06");
  });

  it.each([
    [404, "JOB_NOT_FOUND", "Результат не найден"],
    [409, "RESULT_VIEW_INCONSISTENT", "Данные временно не согласованы"],
    [503, "RESULT_VIEW_UNAVAILABLE", "Результат временно недоступен"],
  ] as const)("renders controlled initial HTTP %s state", async (status, code, title) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(productErrorResponse(code, status)));
    renderPage();
    expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
    expect(screen.queryByText(/RESULT_VIEW_/)).not.toBeInTheDocument();
  });

  it("distinguishes a result that is not ready from a missing calculation", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(productErrorResponse("RESOURCE_NOT_READY", 404)));
    renderPage();
    expect(await screen.findByRole("heading", { name: "Результат еще не готов" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Открыть ход расчета" })).toHaveAttribute(
      "href",
      `/calculations/${JOB_ID}/progress`,
    );
  });

  it("fails closed for an unsupported initial result contract", async () => {
    const invalid = { ...createRecommendedJobResultFixture(), contract_name: "job_result_view_v2" };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(invalid)));
    renderPage();
    expect(await screen.findByRole("heading", { name: "Формат результата не поддерживается" })).toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  });

  it("shows media-plan 422 as an inline state without replacing the result", async () => {
    const result = createRecommendedJobResultFixture();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.pathname.endsWith("/result-view")) return jsonResponse(result);
      if (url.pathname.endsWith("/media-plan")) return jsonResponse({ detail: "hidden" }, 422);
      return jsonResponse({}, 500);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage(`/calculations/${JOB_ID}/result?tab=media-plan`);
    expect(await screen.findByRole("heading", { name: "Такие параметры пока не поддерживаются" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: result.campaign.campaign_name })).toBeInTheDocument();
    expect(screen.queryByText("hidden")).not.toBeInTheDocument();
  });

  it("keeps the last validated result snapshot when refresh fails", async () => {
    const result = createRecommendedJobResultFixture();
    let resultRequests = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.pathname.endsWith("/result-view")) {
        resultRequests += 1;
        if (resultRequests === 1) return jsonResponse(result);
        throw new TypeError("network unavailable");
      }
      return jsonResponse({}, 500);
    });
    vi.stubGlobal("fetch", fetchMock);
    const queryClient = renderPage();
    expect(await screen.findByRole("heading", { name: result.campaign.campaign_name })).toBeInTheDocument();

    await act(async () => {
      await queryClient.refetchQueries({ queryKey: ["job-result-view", JOB_ID] });
    });

    expect(screen.getByRole("heading", { name: result.campaign.campaign_name })).toBeInTheDocument();
    expect(await screen.findByText(/Последний полученный снимок сохранен/)).toBeInTheDocument();
  });
});
