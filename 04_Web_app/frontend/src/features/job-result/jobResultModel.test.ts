import { describe, expect, it } from "vitest";
import {
  parseJobResultView,
  parseScenarioMediaPlan,
} from "../../shared/api/job-result-client";
import {
  createBestRawJobResultFixture,
  createJobResultViewFixture,
  createNoSafeJobResultFixture,
  createPartialCoverageJobResultFixture,
  createReportFailedJobResultFixture,
  createReportReadyJobResultFixture,
  createReportUnavailableJobResultFixture,
  createScenarioMediaPlanFixture,
  createUnavailableJobResultFixture,
} from "../../test/jobResultFixtures";
import {
  SCENARIO_PRESENTATION,
  defaultMediaPlanScenarioId,
  dedupeScenarioIds,
  fixedScenarioLabel,
  formatMetricRange,
  formatMetricValue,
  isPartialCoverage,
  isResultTabId,
  mediaPlanScenarioFromSearch,
  overviewScenarioIds,
  resultSearchParams,
  resultTabFromSearch,
} from "./jobResultModel";

describe("job result presentation model", () => {
  it("accepts only the four published tab query values", () => {
    expect(isResultTabId("overview")).toBe(true);
    expect(isResultTabId("scenarios")).toBe(true);
    expect(isResultTabId("media-plan")).toBe(true);
    expect(isResultTabId("report")).toBe(true);
    expect(isResultTabId("optimizer")).toBe(false);
    expect(resultTabFromSearch("unknown")).toBe("overview");
  });

  it("keeps the fixed source and benchmark product semantics", () => {
    const view = createJobResultViewFixture();
    expect(fixedScenarioLabel(view.scenarios[0])).toBe("Как загружено");
    expect(SCENARIO_PRESENTATION.S01.marker).toBe("Исходный план");
    expect(fixedScenarioLabel(view.scenarios[4])).toBe("Устойчивый ориентир");
    expect(SCENARIO_PRESENTATION.S05.marker).toBe("Устойчивый ориентир");
  });

  it("shows S1, S5 and recommendation without duplicate cards", () => {
    expect(overviewScenarioIds(createJobResultViewFixture())).toEqual(["S01", "S05", "S06"]);
    expect(
      overviewScenarioIds(createJobResultViewFixture({ recommendedScenarioId: "S05" })),
    ).toEqual(["S01", "S05"]);
    expect(dedupeScenarioIds(["S01", null, "S05", "S01", undefined])).toEqual([
      "S01",
      "S05",
    ]);
  });

  it("does not turn S1 into a recommendation in no-safe state", () => {
    const view = createNoSafeJobResultFixture();
    expect(view.recommendation.status).toBe("no_safe_recommendation");
    expect(view.recommendation.scenario_id).toBeNull();
    expect(view.scenarios.every((scenario) => !scenario.is_recommended)).toBe(true);
    expect(overviewScenarioIds(view)).toEqual(["S01", "S05"]);
  });

  it("uses recommendation, then S5, then S1 as the media-plan view default", () => {
    expect(defaultMediaPlanScenarioId(createJobResultViewFixture())).toBe("S06");

    const noSafe = createNoSafeJobResultFixture();
    expect(defaultMediaPlanScenarioId(noSafe)).toBe("S05");

    const sourceFallback = createJobResultViewFixture({
      recommendationStatus: "unavailable",
      unavailableScenarioIds: ["S05", "S06"],
    });
    expect(defaultMediaPlanScenarioId(sourceFallback)).toBe("S01");
  });

  it("treats a media-plan scenario switch as URL-only view state", () => {
    const view = createJobResultViewFixture();
    const recommendationBefore = structuredClone(view.recommendation);

    expect(mediaPlanScenarioFromSearch(view, "S01")).toBe("S01");
    expect(resultSearchParams("media-plan", "S01").toString()).toBe(
      "tab=media-plan&scenario=S01",
    );
    expect(view.recommendation).toEqual(recommendationBefore);
  });

  it("falls back from an unavailable or malformed media-plan query scenario", () => {
    const view = createUnavailableJobResultFixture();
    expect(mediaPlanScenarioFromSearch(view, "S06")).toBe("S05");
    expect(mediaPlanScenarioFromSearch(view, "candidate_opaque")).toBe("S05");
  });

  it("keeps missing metric values distinct from real zero", () => {
    expect(formatMetricValue(null, "RUB")).toBe("Нет данных");
    expect(formatMetricValue(0, "RUB")).toContain("0");

    const unavailable = createJobResultViewFixture().scenarios[0].metrics.avg_basket_delta_rub;
    expect(formatMetricRange(unavailable)).toBe("Нет данных");
  });

  it("keeps best-raw evidence separate from canonical recommendation", () => {
    const view = createBestRawJobResultFixture();
    expect(view.best_raw.available).toBe(true);
    expect(view.best_raw.raw_rank).toBe(1);
    expect(view.best_raw.reason_not_recommended).not.toBeNull();
    expect(view.recommendation.status).toBe("recommended");
    expect(view.recommendation.scenario_id).toBe("S06");
    expect(view.recommendation.raw_rank).toBe(2);
  });

  it("represents partial model coverage without treating it as zero effect", () => {
    const view = createPartialCoverageJobResultFixture();
    expect(isPartialCoverage(view)).toBe(true);
    expect(view.warnings.find((warning) => warning.code === "partial_model_coverage")?.display_text).toContain(
      "не считается нулевым эффектом",
    );
  });

  it("provides honest ready, failed and unavailable report fixtures", () => {
    const ready = createReportReadyJobResultFixture().report;
    expect(ready.status).toBe("ready");
    expect(ready.artifact?.download_path).toMatch(
      /^\/api\/v1\/artifacts\/[a-z][a-z0-9_]*_[0-9a-f]{12,64}\/download$/,
    );
    expect(ready.sheets.length).toBeGreaterThan(0);

    const failed = createReportFailedJobResultFixture().report;
    expect(failed.status).toBe("failed");
    expect(failed.artifact).toBeNull();
    expect(failed.sheets).toEqual([]);

    const unavailable = createReportUnavailableJobResultFixture().report;
    expect(unavailable.status).toBe("unavailable");
    expect(unavailable.artifact).toBeNull();
  });

  it("creates isolated fixtures so one test cannot mutate another", () => {
    const first = createJobResultViewFixture();
    const second = createJobResultViewFixture();
    first.campaign.campaign_name = "Изменено тестом";
    expect(second.campaign.campaign_name).not.toBe("Изменено тестом");
  });

  it("creates fixtures accepted directly by both fail-closed runtime parsers", () => {
    const resultFixtures = [
      createJobResultViewFixture(),
      createNoSafeJobResultFixture(),
      createBestRawJobResultFixture(),
      createUnavailableJobResultFixture(),
      createPartialCoverageJobResultFixture(),
      createReportFailedJobResultFixture(),
      createReportUnavailableJobResultFixture(),
    ];
    for (const resultFixture of resultFixtures) {
      expect(parseJobResultView(resultFixture, resultFixture.job_id)).toBe(resultFixture);
    }
    const result = resultFixtures[0];
    const plan = createScenarioMediaPlanFixture({ resultView: result, scenarioId: "S06" });
    expect(
      parseScenarioMediaPlan(plan, result.job_id, result, {
        scenarioId: "S06",
        page: 1,
        pageSize: 100,
      }),
    ).toBe(plan);
  });

  it("creates reconciled scenario media-plan fixtures with controlled unavailable blocks", () => {
    const plan = createScenarioMediaPlanFixture({ scenarioId: "S05", pageSize: 2 });
    expect(plan.scenario.scenario_id).toBe("S05");
    expect(plan.rows).toHaveLength(2);
    expect(plan.pagination.total_pages).toBe(2);
    expect(plan.totals.selected_budget_rub + plan.totals.unallocated_budget_rub).toBe(
      plan.totals.requested_budget_rub,
    );
    expect(plan.map.geo_points).toBeNull();
    expect(plan.aggregates.by_date.rows).toBeNull();
    expect(plan.working_media_plan.artifact).toBeNull();
  });

  it("creates filtered media-plan data without recomputing full source-of-truth aggregates", () => {
    const plan = createScenarioMediaPlanFixture({
      scenarioId: "S06",
      channel: "Онлайн-видео",
    });
    expect(plan.rows.every((row) => row.channel === "Онлайн-видео")).toBe(true);
    expect(plan.filtered_totals.source_budget_rub).toBe(7_000_000);
    expect(plan.aggregates.by_channel).toHaveLength(2);
  });
});
