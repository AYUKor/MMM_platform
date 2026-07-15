import type { X5MMMDecisionResultV1 as DecisionResultV1 } from "../../shared/api/generated/decision-result-v1";

export type { DecisionResultV1 };
export type CampaignResult = DecisionResultV1["campaign_results"][number];
export type ScenarioResult = CampaignResult["scenarios"][number];
export type QuantileMetric = NonNullable<
  ScenarioResult["metrics"]
>["incremental_turnover"];
