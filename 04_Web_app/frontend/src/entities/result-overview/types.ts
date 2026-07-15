import type { X5MMMResultOverviewV1 as ResultOverviewV1 } from "../../shared/api/generated/result-overview-v1";

export type { ResultOverviewV1 };
export type OverviewCampaign = ResultOverviewV1["campaigns"][number];
export type OverviewScenario = OverviewCampaign["scenarios"][number];
export type OverviewWarning = ResultOverviewV1["warnings"][number];
export type OverviewArtifact = ResultOverviewV1["artifacts"][number];
export type AllocationLine = OverviewCampaign["allocation_comparison"][number];
export type QuantileMetric = NonNullable<
  OverviewScenario["metrics"]["incremental_turnover"]
>;
