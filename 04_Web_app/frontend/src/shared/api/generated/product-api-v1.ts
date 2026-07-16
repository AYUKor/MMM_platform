/* Generated from ../../contracts/product_api_v1.schema.json. Do not edit manually. */

export type X5MMMProductAPIV1 = ModelPassport | HttpErrorCatalog | JobList | CalculationProfile;
export type NullableString = string | null;

export interface ModelPassport {
  contract_name: "model_passport_v1";
  schema_version: "1.0.0";
  record_origin: "verified_model_package" | "synthetic_fixture";
  serving: {
    deployment_profile: "local_development" | "research_pilot";
    display_name: string;
    calculation_allowed: boolean;
    decision_scope: "forecast_and_allocation_only";
    production_claim_allowed: false;
  };
  package: {
    registry_channel: string;
    registry_event_id: string;
    package_id: string;
    package_fingerprint: string;
    model_run_id: string;
    package_stage: string;
    activation_status: string;
    package_schema_version: string;
    gate_policy_version: string;
  };
  data: {
    grain: "daily";
    training_period: RequiredPeriod;
    development_shadow_period: NullablePeriod;
  };
  coverage: {
    segments: string[];
    channels: string[];
    targets: TargetSummary[];
    geographies_n: number;
    capability_cells_n: number;
    allowed_use_counts: {
      primary?: number;
      caution?: number;
      diagnostic?: number;
      unavailable?: number;
    };
    channel_policies: ChannelPolicy[];
  };
  validation: {
    historical_replay: EvidenceStatus;
    sealed_oot: EvidenceStatus;
    production_blockers: Status[];
  };
  caveats: Status[];
}
export interface RequiredPeriod {
  start_date: string;
  end_date: string;
}
export interface NullablePeriod {
  start_date: string | null;
  end_date: string | null;
  purpose: "development_shadow_not_sealed_oot";
}
export interface TargetSummary {
  target: string;
  allowed_use_counts: {
    [k: string]: number;
  };
  objective_roles: string[];
}
export interface ChannelPolicy {
  segment: string;
  channel: string;
  target: string;
  allowed_use: "primary" | "caution" | "diagnostic" | "unavailable";
  forecast_action: string;
  optimizer_action: string;
  display_text: string;
}
export interface EvidenceStatus {
  status: "passed" | "unavailable" | "failed";
  generated_at_utc: NullableString;
  reason_code: NullableString;
  display_text: string;
}
export interface Status {
  code: string;
  display_text: string;
}
export interface HttpErrorCatalog {
  contract_name: "http_error_catalog_v1";
  schema_version: "1.0.0";
  errors: {
    code: string;
    http_status: number;
    retryable: boolean;
    display_text: string;
    user_action: string;
  }[];
}
export interface JobList {
  contract_name: "job_list_v1";
  schema_version: "1.0.0";
  items: {
    [k: string]: unknown;
  }[];
  total: number;
  limit: number;
  offset: number;
  next_offset: number | null;
}
export interface CalculationProfile {
  contract_name: "calculation_profile_v1";
  schema_version: "1.0.0";
  scenario6_attempt_budget: number;
  profile_label: string;
  model_version_label: string;
}
