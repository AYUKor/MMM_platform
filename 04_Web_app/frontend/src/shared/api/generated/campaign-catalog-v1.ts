/* Generated from ../../contracts/campaign_catalog_v1.schema.json. Do not edit manually. */

export type OptionalRange = null | Range;

/**
 * Past-campaign catalog of the active model package, served exactly as the package extension campaign_catalog_v1 holds it. The portal never recomputes the numbers.
 */
export interface CampaignCatalogV1 {
  contract_name: "campaign_catalog_v1";
  schema_version: "1.1.0";
  record_origin: "verified_model_package_artifact" | "model_package_artifact_unavailable";
  status: "available" | "unavailable";
  title: "Прошлые кампании";
  display_text: string;
  package_id: string;
  model_version: string | null;
  model_display_name: string | null;
  artifact_id: string | null;
  catalog_version: string | null;
  period_start: string | null;
  period_end: string | null;
  roas_level_label: string | null;
  summary: null | Summary;
  download: null | Download;
  notes: Note[];
  campaigns: Campaign[];
  updated_at_utc: string | null;
}
export interface Summary {
  campaigns_n: number;
  computed_n: number;
  reliable_n: number;
  up_to_120_days_n: number;
  longer_120_days_n: number;
  budget_rub: number;
  computed_budget_rub: number;
  turnover_increment_rub: number;
  weighted_roas: number | null;
}
export interface Download {
  file_name: string;
  size_bytes: number;
  sha256: string;
  download_path: "/api/v1/campaign-catalog/download";
  /**
   * @minItems 3
   * @maxItems 3
   */
  sheets: [string, string, string];
}
export interface Note {
  code: string;
  display_text: string;
}
export interface Campaign {
  number: number;
  name: string;
  /**
   * @minItems 1
   */
  directions: [
    "ТС5/Онлайн" | "ТС5/Оффлайн" | "ТСХ/Онлайн" | "ТСХ/Оффлайн",
    ...("ТС5/Онлайн" | "ТС5/Оффлайн" | "ТСХ/Онлайн" | "ТСХ/Оффлайн")[]
  ];
  start_date: string;
  end_date: string;
  days_n: number;
  duration_group: "up_to_120_days" | "120_days_and_longer";
  budget_rub: number;
  /**
   * @minItems 1
   */
  channels: [Channel, ...Channel[]];
  main_channel_id: "Digital_Performance" | "OOH_Total" | "Indoor" | "Радио" | "Нац_ТВ" | "Рег_ТВ";
  cities: string[];
  nationwide_channels: string[];
  status: "computed" | "not_computed";
  status_display_text: string | null;
  turnover_increment_rub: OptionalRange;
  orders_per_1000_buyers: OptionalRange;
  avg_basket_increment_rub: OptionalRange;
  roas: OptionalRange;
  overlaps_n: number;
  reliable: 0 | 1;
  explanation: null | Explanation;
}
export interface Channel {
  channel_id: "Digital_Performance" | "OOH_Total" | "Indoor" | "Радио" | "Нац_ТВ" | "Рег_ТВ";
  display_name: "Цифровая реклама" | "Наружная реклама" | "Indoor" | "Радио" | "Национальное ТВ" | "Региональное ТВ";
  budget_rub: number;
  nationwide: boolean;
}
export interface Range {
  estimate: number;
  low: number;
  high: number;
}
/**
 * Why the campaign got its number: the first-ruble potential split into kept effect, loss to the campaign's own saturation and loss to other ads in the same weeks and cities, plus up to three reasons from the versioned rule file, only when something specific to the campaign can be said (none otherwise: the card shows the split only). Explains the catalog numbers, never changes them.
 */
export interface Explanation {
  rules_version: string;
  potential_turnover_rub: number;
  kept_share: number;
  own_saturation_share: number;
  overlap_share: number;
  first_ruble_roas: number;
  typical_first_ruble_roas: number;
  unseen_budget_share: number;
  tail_share: number;
  /**
   * @maxItems 2
   */
  own_saturation_cities: [] | [string] | [string, string];
  /**
   * @maxItems 2
   */
  overlap_cities: [] | [string] | [string, string];
  /**
   * @minItems 0
   * @maxItems 3
   */
  reasons: [] | [Note] | [Note, Note] | [Note, Note, Note];
}
