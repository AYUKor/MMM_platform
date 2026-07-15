import type {
  OverviewCampaign,
  ResultOverviewV1,
} from "../../entities/result-overview/types";

export type CampaignSelection =
  | { status: "selected"; campaign: OverviewCampaign }
  | { status: "empty" }
  | { status: "selection-required"; campaigns: OverviewCampaign[] }
  | { status: "not-found"; requestedCampaignId: string };

export function selectCampaign(
  result: ResultOverviewV1,
  requestedCampaignId?: string | null,
): CampaignSelection {
  const campaigns = result.campaigns;

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
