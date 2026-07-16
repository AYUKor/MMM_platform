import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import {
  createBestRawJobResultFixture,
  createNoSafeJobResultFixture,
  createReportFailedJobResultFixture,
  createReportReadyJobResultFixture,
  createReportUnavailableJobResultFixture,
  createRecommendedJobResultFixture,
  createScenarioMediaPlanFixture,
} from "../../test/jobResultFixtures";
import type { JobResultViewV1, ScenarioId } from "../../shared/api/generated/job-result-view-v1";
import type { ScenarioMediaPlanV1 } from "../../shared/api/generated/scenario-media-plan-v1";
import type { MediaPlanControls } from "./MediaPlanTab";
import type { ResultMetricId } from "./jobResultFormatting";
import { JobResultView, type JobResultViewProps } from "./JobResultView";
import type { ResultTabId } from "./jobResultModel";

const DEFAULT_CONTROLS: MediaPlanControls = {
  channel: null,
  geo: null,
  page: 1,
  pageSize: 25,
};

interface RenderOptions {
  result?: JobResultViewV1;
  activeTab?: ResultTabId;
  mediaPlan?: ScenarioMediaPlanV1;
  mediaScenarioId?: ScenarioId | null;
  overrides?: Partial<JobResultViewProps>;
}

function renderResultView({
  result = createRecommendedJobResultFixture(),
  activeTab = "overview",
  mediaPlan,
  mediaScenarioId = "S06",
  overrides = {},
}: RenderOptions = {}) {
  const props: JobResultViewProps = {
    result,
    activeTab,
    metricId: "incremental_turnover_rub",
    mediaPlan,
    mediaScenarioId,
    mediaControls: DEFAULT_CONTROLS,
    mediaLoading: false,
    mediaError: null,
    refreshNotice: null,
    onTabChange: vi.fn(),
    onMetricChange: vi.fn(),
    onMediaScenarioChange: vi.fn(),
    onMediaControlsChange: vi.fn(),
    onMediaPageChange: vi.fn(),
    onMediaRetry: vi.fn(),
    onRefresh: vi.fn(),
    ...overrides,
  };
  return {
    ...render(
      <MemoryRouter>
        <JobResultView {...props} />
      </MemoryRouter>,
    ),
    props,
  };
}

function ResultViewHarness({ result }: { result: JobResultViewV1 }) {
  const [tab, setTab] = useState<ResultTabId>("overview");
  const [scenarioId, setScenarioId] = useState<ScenarioId>("S06");
  const [metricId, setMetricId] = useState<ResultMetricId>("incremental_turnover_rub");
  const plan = createScenarioMediaPlanFixture({
    resultView: result,
    scenarioId,
    pageSize: 25,
  });
  return (
    <MemoryRouter>
      <JobResultView
        result={result}
        activeTab={tab}
        metricId={metricId}
        mediaPlan={plan}
        mediaScenarioId={scenarioId}
        mediaControls={DEFAULT_CONTROLS}
        mediaLoading={false}
        mediaError={null}
        refreshNotice={null}
        onTabChange={setTab}
        onMetricChange={setMetricId}
        onMediaScenarioChange={setScenarioId}
        onMediaControlsChange={() => undefined}
        onMediaPageChange={() => undefined}
        onMediaRetry={() => undefined}
        onRefresh={() => undefined}
      />
    </MemoryRouter>
  );
}

describe("JobResultView", () => {
  it("exposes all four product tabs and switches their controlled panels", () => {
    render(<ResultViewHarness result={createRecommendedJobResultFixture()} />);
    expect(screen.getAllByRole("tab")).toHaveLength(4);
    expect(screen.getByRole("heading", { name: "Рекомендуемое распределение бюджета" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Сценарии и надежность" }));
    expect(screen.getByRole("heading", { name: "Сравнение рассчитанных вариантов" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Медиаплан" }));
    expect(screen.getByRole("heading", { name: "Медиаплан было → рекомендуется" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Отчет" }));
    expect(screen.getByRole("heading", { name: "Отчет готов" })).toBeInTheDocument();
  });

  it("keeps S1 as source and S5 as the stable reference", () => {
    renderResultView();
    expect(screen.getAllByText("Исходный план").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Как загружено").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Устойчивый ориентир").length).toBeGreaterThan(0);
  });

  it("renders unavailable metric data as missing rather than zero", () => {
    const result = createRecommendedJobResultFixture();
    expect(result.scenarios[5].metrics.avg_basket_delta_rub.p50).toBeNull();
    expect(result.reliability.score).toBeNull();
    renderResultView({ result });
    expect(screen.getByText("Изменение среднего чека пока недоступно")).toBeInTheDocument();
    expect(screen.getByText("Числовая шкала пока недоступна")).toBeInTheDocument();
    expect(screen.queryByText("0/10")).not.toBeInTheDocument();
  });

  it("still renders a real known zero without treating it as missing", () => {
    const result = createRecommendedJobResultFixture();
    result.scenarios[5].budget.allocated_budget_rub = result.scenarios[5].budget.requested_budget_rub;
    result.scenarios[5].budget.unallocated_budget_rub = 0;
    renderResultView({ result });
    expect(screen.getByText("Не распределено").nextElementSibling).toHaveTextContent(/^0/);
    expect(screen.getByText("Изменение среднего чека пока недоступно")).toBeInTheDocument();
  });

  it("shows both published recommendation ranks without reordering scenarios", () => {
    renderResultView();
    expect(screen.getByText("Место среди устойчивых").nextElementSibling).toHaveTextContent("№ 1");
    expect(screen.getByText("Место без учета ограничений").nextElementSibling).toHaveTextContent("№ 1");
  });

  it("explains no-safe recommendation without promoting S1 or S5", () => {
    renderResultView({ result: createNoSafeJobResultFixture() });
    expect(
      screen.getByRole("heading", { name: "Безопасная автоматическая рекомендация не сформирована" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Ни один из них не становится победителем автоматически/)).toBeInTheDocument();
    expect(screen.queryByText("Рекомендован системой")).not.toBeInTheDocument();
  });

  it("shows best raw only as a non-recommended diagnostic", () => {
    renderResultView({
      result: createBestRawJobResultFixture(),
      activeTab: "scenarios",
    });
    expect(
      screen.getByRole("heading", { name: "Математически сильный, но не рекомендованный вариант" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Только для проверки расчета").length).toBeGreaterThan(0);
    expect(screen.getByText("Не является рекомендацией")).toBeInTheDocument();
  });

  it("uses only the canonical artifact path for a ready report", () => {
    const result = createReportReadyJobResultFixture();
    renderResultView({ result, activeTab: "report" });
    const downloads = screen.getAllByRole("link", { name: "Скачать отчет" });
    expect(downloads).toHaveLength(2);
    for (const download of downloads) {
      expect(download).toHaveAttribute(
        "href",
        `http://127.0.0.1:8765${result.report.artifact?.download_path}`,
      );
      expect(download).toHaveAttribute("download");
    }
    expect(screen.getByRole("heading", { name: "Листы отчета" })).toBeInTheDocument();
  });

  it("renders a contract-backed working media-plan artifact when it is ready", () => {
    const result = createReportReadyJobResultFixture();
    const workingPlan = {
      status: "ready" as const,
      display_text: "Рабочий медиаплан готов.",
      artifact: {
        artifact_id: "artifact_1234567890abcdef",
        display_name: "working_media_plan.xlsx",
        media_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes: 32_768,
        sha256: "c".repeat(64),
        download_path: "/api/v1/artifacts/artifact_1234567890abcdef/download",
      },
    };
    result.media_plan.working_media_plan = structuredClone(workingPlan);
    result.report.working_media_plan = structuredClone(workingPlan);
    renderResultView({ result, activeTab: "report" });
    expect(screen.getByRole("heading", { name: "working_media_plan.xlsx" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Скачать медиаплан" })).toHaveAttribute(
      "href",
      "http://127.0.0.1:8765/api/v1/artifacts/artifact_1234567890abcdef/download",
    );
  });

  it.each([
    [createReportFailedJobResultFixture(), "Не удалось сформировать отчет"],
    [createReportUnavailableJobResultFixture(), "Отчет недоступен"],
  ] as const)("does not invent a download for a non-ready report", (result, title) => {
    renderResultView({ result, activeTab: "report" });
    expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Скачать отчет" })).not.toBeInTheDocument();
  });

  it("changes only the viewed media plan when a scenario radio is selected", () => {
    const result = createRecommendedJobResultFixture();
    const recommendationBefore = structuredClone(result.recommendation);
    const onMediaScenarioChange = vi.fn();
    renderResultView({
      result,
      activeTab: "media-plan",
      mediaPlan: createScenarioMediaPlanFixture({ resultView: result, scenarioId: "S06", pageSize: 25 }),
      overrides: { onMediaScenarioChange },
    });
    fireEvent.click(screen.getByRole("radio", { name: /S1.*Как загружено/ }));
    expect(onMediaScenarioChange).toHaveBeenCalledWith("S01");
    expect(result.recommendation).toEqual(recommendationBefore);
    expect(screen.getByText(/Рекомендация системы, ранги и выводы расчета при этом не меняются/)).toBeInTheDocument();
  });

  it("shows requested total, row delta percent and aggregate quality from the media contract", () => {
    const result = createRecommendedJobResultFixture();
    renderResultView({
      result,
      activeTab: "media-plan",
      mediaPlan: createScenarioMediaPlanFixture({ resultView: result, scenarioId: "S06", pageSize: 25 }),
    });
    expect(screen.getByText("Запрошенный бюджет").nextElementSibling).toHaveTextContent("12");
    expect(screen.getByRole("columnheader", { name: "Изменение, %" })).toBeInTheDocument();
    expect(screen.getAllByText("Строка прошла опубликованные проверки качества.").length).toBeGreaterThan(0);
  });
});
