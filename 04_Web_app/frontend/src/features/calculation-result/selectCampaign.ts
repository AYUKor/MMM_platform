import type {
  CampaignResult,
  DecisionResultV1,
} from "../../entities/decision-result/types";

export type CampaignSelection =
  | { status: "selected"; campaign: CampaignResult }
  | { status: "empty" }
  | { status: "selection-required"; campaigns: CampaignResult[] }
  | { status: "not-found"; requestedCampaignId: string };

export function selectCampaign(
  result: DecisionResultV1,
  requestedCampaignId?: string | null,
): CampaignSelection {
  const campaigns = result.campaign_results;

  if (campaigns.length === 0) return { status: "empty" };

  if (requestedCampaignId) {
    const campaign = campaigns.find(
      (candidate) => candidate.campaign_id === requestedCampaignId,
    );
    return campaign
      ? { status: "selected", campaign }
      : { status: "not-found", requestedCampaignId };
  }

  if (campaigns.length === 1) {
    const [campaign] = campaigns;
    if (!campaign) return { status: "empty" };
    return { status: "selected", campaign };
  }

  return { status: "selection-required", campaigns };
}
