import { describe, expect, it } from "vitest";
import fixture from "../../../../tests/fixtures/result_overview_v1_real_sanitized.json";
import type { ResultOverviewV1 } from "../../entities/result-overview/types";
import { buildResultOverviewModel } from "./buildResultOverviewModel";

function resultAndCampaign() {
  const result = structuredClone(fixture) as unknown as ResultOverviewV1;
  const [campaign] = result.campaigns;
  return { result, campaign };
}

describe("buildResultOverviewModel", () => {
  it("uses only direct overview metrics and keeps their semantics", () => {
    const { result, campaign } = resultAndCampaign();
    const model = buildResultOverviewModel(result, campaign);

    expect(model.recommendedScenario.id).toBe("S06");
    expect(model.benchmarkScenario.id).toBe("S05");
    expect(model.metrics.find((metric) => metric.id === "roas")?.p10).toBe(
      campaign.recommendation.metrics.turnover_roas?.p10,
    );
    expect(model.metrics.find((metric) => metric.id === "orders")?.available).toBe(true);
    expect(model.metrics.find((metric) => metric.id === "orders")?.note).toContain(
      "без нормализации",
    );
    expect(model.metrics.find((metric) => metric.id === "basket-bridge")?.note).toContain(
      "не изменение среднего чека",
    );
  });

  it("uses server-provided allocation deltas without rebuilding them", () => {
    const { result, campaign } = resultAndCampaign();
    const model = buildResultOverviewModel(result, campaign);

    expect(model.allocations[0]?.deltaBudgetRub).toBe(
      campaign.allocation_comparison[0].delta_budget_rub,
    );
    expect(model.recommendation.movedBudgetRub).toBe(
      campaign.recommendation.versus_uploaded_plan.moved_budget_rub,
    );
  });

  it("never exposes raw warning text or opaque candidate ids", () => {
    const { result, campaign } = resultAndCampaign();
    campaign.warnings[0].display_text = "RAW_SUPPORT_BACKEND_MESSAGE";
    const model = buildResultOverviewModel(result, campaign);
    const serialized = JSON.stringify(model);

    expect(serialized).not.toContain("RAW_SUPPORT_BACKEND_MESSAGE");
    expect(serialized).not.toContain("candidate_");
    expect(model.warnings[0]?.action).toContain("Проверьте");
  });

  it("preserves the controlled S6 unavailable state", () => {
    const { result, campaign } = resultAndCampaign();
    const s6 = campaign.scenarios.find((scenario) => scenario.scenario_id === "S06");
    if (!s6) throw new Error("S6 is required by contract");
    s6.available = false;
    s6.metrics = {
      incremental_turnover: null,
      turnover_roas: null,
      incremental_orders: null,
      incremental_orders_usage: "diagnostic_only",
      avg_basket_turnover_bridge: null,
    };
    campaign.scenario6.best_raw = null;
    campaign.scenario6.best_safe = null;
    campaign.scenario6.raw_differs_from_safe = false;
    campaign.scenario6.audit.run_status.code = "gate_policy_blocked";
    const model = buildResultOverviewModel(result, campaign);

    expect(model.s6.available).toBe(false);
    expect(model.s6.message).toContain("не сформирован");
    expect(model.search.bestSafe.available).toBe(false);
  });

  it("exposes only marketer-facing downloads", () => {
    const { result, campaign } = resultAndCampaign();
    const model = buildResultOverviewModel(result, campaign);

    expect(model.downloads.map((download) => download.kind)).toEqual([
      "report",
      "media-plan",
    ]);
    expect(JSON.stringify(model.downloads)).not.toContain("storage_key");
  });
});
