import { describe, expect, it } from "vitest";
import gateBlockedFixture from "../../../../tests/fixtures/decision_result_v1_gate_blocked_sanitized.json";
import safeFixture from "../../../../tests/fixtures/decision_result_v1_real_sanitized.json";
import type { DecisionResultV1 } from "../../entities/decision-result/types";
import { buildResultOverviewModel } from "./buildResultOverviewModel";

function soleCampaign(result: DecisionResultV1) {
  const [campaign, extraCampaign] = result.campaign_results;
  if (!campaign || extraCampaign) throw new Error("Expected one sanitized campaign");
  return campaign;
}

describe("buildResultOverviewModel", () => {
  it("uses direct contract metrics and leaves missing projections unavailable", () => {
    const result = safeFixture as unknown as DecisionResultV1;
    const model = buildResultOverviewModel(result, soleCampaign(result));

    expect(model.recommendedScenario.id).toBe("S06");
    expect(model.benchmarkScenario.id).toBe("S05");
    expect(model.metrics.find((metric) => metric.id === "roas")?.p10).toBeNull();
    expect(model.metrics.find((metric) => metric.id === "orders-per-100k")?.available).toBe(false);
    expect(model.metrics.find((metric) => metric.id === "basket-delta")?.available).toBe(false);
    expect(model.recommendation.reliability).toBeNull();
  });

  it("preserves S6 unavailable reason and recommends S1 without a launch claim", () => {
    const result = gateBlockedFixture as unknown as DecisionResultV1;
    const model = buildResultOverviewModel(result, soleCampaign(result));

    expect(model.recommendedScenario.id).toBe("S01");
    expect(model.s6.available).toBe(false);
    expect(model.s6.explanation).toContain("недоступен");
    expect(model.recommendation.allocationOnlyNotice).toContain("не является решением");
  });
});
