/* Generated from ../../contracts/campaign_card_v1.schema.json. Do not edit manually. */

export type OptionalRange = null | Range;

/**
 * One past campaign of the active package's catalog (the same record as in campaign_catalog_v1).
 */
export interface CampaignCardV1 {
  contract_name: "campaign_card_v1";
  schema_version: "1.0.0";
  record_origin: "verified_model_package_artifact";
  package_id: string;
  model_version: string;
  model_display_name: string;
  artifact_id: string;
  catalog_version: string;
  period_start: string;
  period_end: string;
  roas_level_label: string;
  notes: Note[];
  campaign: Campaign;
  updated_at_utc: string;
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
