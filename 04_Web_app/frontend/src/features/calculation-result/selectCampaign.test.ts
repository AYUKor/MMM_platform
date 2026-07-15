import { describe, expect, it } from "vitest";
import fixture from "../../../../tests/fixtures/decision_result_v1_real_sanitized.json";
import type { DecisionResultV1 } from "../../entities/decision-result/types";
import { selectCampaign } from "./selectCampaign";

const result = fixture as unknown as DecisionResultV1;

describe("selectCampaign", () => {
  it("selects the only campaign", () => {
    const selection = selectCampaign(result);
    expect(selection.status).toBe("selected");
  });

  it("requires an explicit selection for a multi-campaign result", () => {
    const [campaign] = result.campaign_results;
    if (!campaign) throw new Error("Sanitized fixture must contain a campaign");
    const multiCampaignResult: DecisionResultV1 = {
      ...result,
      campaign_results: [
        campaign,
        { ...campaign, campaign_id: "campaign_second_sanitized" },
      ],
    };

    const selection = selectCampaign(multiCampaignResult);
    expect(selection.status).toBe("selection-required");
  });

  it("does not fall back to the first campaign for an unknown id", () => {
    expect(selectCampaign(result, "missing_campaign")).toEqual({
      status: "not-found",
      requestedCampaignId: "missing_campaign",
    });
  });
});
