/* Generated from ../../contracts/model_passport_v2.schema.json. Do not edit manually. */

export type NonEmptyText = string;
export type NullableText = string | null;

export interface ModelPassportV2 {
  contract_name: "model_passport_v2";
  schema_version: "2.0.0";
  record_origin: "verified_model_package" | "synthetic_fixture";
  serving: Serving;
  package: Package;
  data: Data;
  coverage: Coverage;
  validation: Validation;
  channel_policies: ChannelPolicy[];
  caveats: Status[];
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
export interface Package {
  registry_channel: NonEmptyText;
  registry_event_id: NonEmptyText;
  package_id: string;
  package_fingerprint: string;
  model_run_id: NonEmptyText;
  package_stage: NonEmptyText;
  activation_status: NonEmptyText;
  package_schema_version: NonEmptyText;
  gate_policy_version: NonEmptyText;
}
export interface Data {
  grain: "daily";
  training_period: Period;
  development_shadow_period: DevelopmentPeriod;
}
export interface Period {
  start_date: string;
  end_date: string;
}
export interface DevelopmentPeriod {
  start_date: string | null;
  end_date: string | null;
  purpose: "development_shadow_not_sealed_oot";
}
export interface Coverage {
  segments: NonEmptyText[];
  channels: Channel[];
  /**
   * @minItems 1
   * @maxItems 1
   */
  targets: [Target];
  geographies_n: number;
  capability_cells_n: number;
}
export interface Channel {
  channel_id: NonEmptyText;
  channel_display_name: NonEmptyText;
}
export interface Target {
  target_id: "turnover";
  core_target: "turnover_per_user";
}
export interface Validation {
  historical_replay: EvidenceStatus;
  sealed_oot: EvidenceStatus;
  production_blockers: Status[];
}
export interface EvidenceStatus {
  status: "passed" | "unavailable" | "failed";
  generated_at_utc: NullableText;
  reason_code: NullableText;
  display_text: NonEmptyText;
}
export interface Status {
  code: NonEmptyText;
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
