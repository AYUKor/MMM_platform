/* Generated from ../../contracts/historical_campaigns_v1.schema.json. Do not edit manually. */

export type HistoricalCampaignsV1 = Registry | Card | Daily | Media;

export interface Registry {
  schema_version: "1.0.0";
  dataset_id: string;
  model_package_id: string;
  method_version: string;
  matches_active_model: boolean | null;
  resource: "registry";
  blocks: {
    segment: string;
    total: number;
    offset: number;
    limit: number;
    items: Campaign[];
    direction_name: string;
  }[];
}
export interface Campaign {
  campaign_key: string;
  source_group_id: string;
  campaign_name: string;
  segment: string;
  start_date: string | null;
  end_date: string | null;
  evaluation_end: string;
  model_package_id: string;
  method_version: string;
  status_text: string;
  business_campaign_id: string | null;
  declared_windows: string[];
  source_budget_rub: number | null;
  allocated_budget_rub: number;
  panel_budget_rub: number;
  evaluated_budget_rub: number;
  has_federal_rows: boolean;
  geographies_count: number;
  result: Result | null;
  identity_status: "confirmed" | "needs_review";
  coverage_status: "full" | "unavailable";
  result_status: "pending" | "calculated" | "unavailable" | "error";
  identity_reasons: string[];
  coverage_reasons: string[];
  reason_texts: string[];
  limitations: string[];
  tail_days: number;
  historical_geographies: string[];
}
export interface Result {
  rto: Quantiles;
  roas: Quantiles;
  during: Quantiles;
  after: Quantiles;
  draws: number;
}
export interface Quantiles {
  p10: number;
  p50: number;
  p90: number;
}
export interface Card {
  schema_version: "1.0.0";
  dataset_id: string;
  model_package_id: string;
  method_version: string;
  matches_active_model: boolean | null;
  resource: "card";
  campaign: Campaign;
}
export interface Daily {
  schema_version: "1.0.0";
  dataset_id: string;
  model_package_id: string;
  method_version: string;
  matches_active_model: boolean | null;
  resource: "daily";
  campaign_key: string;
  items: DailyItem[];
}
export interface DailyItem {
  date: string;
  period: "Размещение" | "После завершения";
  rto: Quantiles;
}
export interface Media {
  schema_version: "1.0.0";
  dataset_id: string;
  model_package_id: string;
  method_version: string;
  matches_active_model: boolean | null;
  resource: "media";
  campaign_key: string;
  plan: PlanRow[];
  geo_channel_totals: GeoChannel[];
  geography_totals: {
    geography: string;
    spend_rub: number;
    rto: Quantiles;
  }[];
  channel_totals: {
    media_channel: string;
    spend_rub: number;
    rto: Quantiles;
  }[];
}
export interface PlanRow {
  date: string;
  geography: string;
  media_channel: string;
  spend_rub: number;
}
export interface GeoChannel {
  geography: string;
  media_channel: string;
  rto: Quantiles;
}
