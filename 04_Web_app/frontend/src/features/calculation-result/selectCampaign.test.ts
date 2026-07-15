import { describe, expect, it } from "vitest";
import fixture from "../../../../tests/fixtures/result_overview_v1_real_sanitized.json";
import type { ResultOverviewV1 } from "../../entities/result-overview/types";
import { selectCampaign } from "./selectCampaign";

const result = fixture as unknown as ResultOverviewV1;

describe("selectCampaign", () => {
  it("selects the only campaign", () => {
    const selection = selectCampaign(result);
    expect(selection.status).toBe("selected");
  });

  it("requires an explicit selection for a multi-campaign result", () => {
    const [campaign] = result.campaigns;
    if (!campaign) throw new Error("Sanitized fixture must contain a campaign");
    const multiCampaignResult: ResultOverviewV1 = {
      ...result,
      campaigns: [
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
