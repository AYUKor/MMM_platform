/* Generated from ../../contracts/model_overview_v2.schema.json. Do not edit manually. */

export type NullableText = string | null;
export type NonEmptyText = string;

export interface ModelOverviewV2 {
  contract_name: "model_overview_v2";
  schema_version: "2.0.0";
  serving: Serving;
  summary: Summary;
  channel_policies: ChannelPolicy[];
  limitations: Limitation[];
}
export interface Serving {
  serving_policy_version: "turnover_serving_v1";
  target_id: "turnover";
  core_target: "turnover_per_user";
  serving_targets_n: 1;
  active_serving_models_n: 4;
  research_models_in_package_n: 12;
  calculation_allowed: boolean;
  production_claim_allowed: false;
}
export interface Summary {
  training_period: Period;
  package_status: NullableText;
  activation_status: NullableText;
  calculation_allowed: boolean;
  historical_replay: EvidenceStatus;
  sealed_oot: EvidenceStatus;
}
export interface Period {
  start_date: string;
  end_date: string;
}
export interface EvidenceStatus {
  status: "passed" | "unavailable" | "failed";
  generated_at_utc: NullableText;
  reason_code: NullableText;
  display_text: NonEmptyText;
}
export interface ChannelPolicy {
  segment: NonEmptyText;
  channel_id: NonEmptyText;
  channel_display_name: NonEmptyText;
  target: "turnover";
  allowed_use: NonEmptyText;
  forecast_action: NonEmptyText;
  optimizer_action: NonEmptyText;
  display_text: NonEmptyText;
}
export interface Limitation {
  code: NonEmptyText;
  display_text: NonEmptyText;
  status?: string;
  title?: string;
  recommended_action?: string;
}
