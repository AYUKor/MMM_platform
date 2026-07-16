/* Generated from ../../contracts/application_lifecycle_v1.schema.json. Do not edit manually. */

/**
 * Wire contracts for uploads, validation, jobs, lifecycle events, progress and application errors.
 */
export type X5MMMApplicationLifecycleV1 =
  CampaignUpload | ValidationResult | DecisionJob | JobEvent | ProgressEvent | ApplicationError;
export type RecordOrigin = "application_runtime" | "synthetic_fixture";
export type OpaqueId = string;
export type UploadStatus = Status & {
  code?: "received" | "parsed" | "rejected";
  [k: string]: unknown;
};
export type NullableDateTime = string | null;
export type StableCode = string;
export type Sha256 = string;
export type NullableString = string | null;
export type NullableNonNegativeInteger = number | null;
export type NullableOpaqueId = OpaqueId | null;
export type ValidationStatus = Status & {
  code?: "running" | "valid" | "invalid";
  [k: string]: unknown;
};
export type StringSet = string[];
export type ModelSelector = {
  [k: string]: unknown;
} & {
  mode: "registry_channel" | "explicit_package";
  registry_channel: NullableString;
  package_id: NullableString;
  expected_package_fingerprint: Sha256 | null;
};
export type JobStatus = Status & {
  code?: "queued" | "running" | "cancel_requested" | "succeeded" | "failed" | "cancelled" | "timed_out";
  [k: string]: unknown;
};

export interface CampaignUpload {
  contract_name: "campaign_upload_v1";
  schema_version: "1.0.0";
  record_origin: RecordOrigin;
  upload_id: OpaqueId;
  actor_id: OpaqueId;
  status: UploadStatus;
  received_at_utc: string;
  parsed_at_utc: NullableDateTime;
  rejected_at_utc: NullableDateTime;
  original_file: ArtifactIdentity;
  parser_name: NullableString;
  parser_version: NullableString;
  parsed_payload: ArtifactIdentity | null;
  source_rows_n: NullableNonNegativeInteger;
  detected_campaigns_n: NullableNonNegativeInteger;
  rejection_error_id: NullableOpaqueId;
}
export interface Status {
  code: string;
  display_text: string;
}
export interface ArtifactIdentity {
  artifact_id: OpaqueId;
  kind: StableCode;
  display_name: string;
  media_type: string;
  sha256: Sha256;
  size_bytes: number;
  storage_key: string;
}
export interface ValidationResult {
  contract_name: "validation_result_v1";
  schema_version: "1.0.0";
  record_origin: RecordOrigin;
  validation_id: OpaqueId;
  upload_id: OpaqueId;
  status: ValidationStatus;
  validator_name: string;
  validator_version: string;
  started_at_utc: string;
  finished_at_utc: NullableDateTime;
  source_payload: ArtifactIdentity;
  model: ResolvedModelReference | null;
  normalized_plan: ArtifactIdentity | null;
  daily_flighting: ArtifactIdentity | null;
  model_validation: ArtifactIdentity | null;
  campaigns: CampaignPreview[];
  totals: ValidationTotals | null;
  blocking_errors: ValidationIssue[];
  warnings: ValidationIssue[];
  job_creation_allowed: boolean;
  preview?: ValidationPreview;
}
export interface ResolvedModelReference {
  registry_channel: string;
  registry_event_id: string;
  package_id: string;
  package_fingerprint: Sha256;
  package_manifest_sha256: Sha256;
  activation_status: string;
  production_blockers: StringSet;
}
export interface CampaignPreview {
  campaign_id: OpaqueId;
  campaign_name: string;
  segments: StringSet & {
    [k: string]: unknown;
  };
  start_date: string;
  end_date: string;
  active_days: number;
  channels: StringSet & {
    [k: string]: unknown;
  };
  geographies: StringSet & {
    [k: string]: unknown;
  };
  creatives: StringSet;
  source_rows_n: number;
  normalized_rows_n: number;
  daily_rows_n: number;
  uploaded_budget_rub: number;
  model_input_budget_rub: number;
  unmodeled_budget_rub: number;
  daily_budget_rub: number;
}
export interface ValidationTotals {
  source_rows_n: number;
  normalized_rows_n: number;
  daily_rows_n: number;
  uploaded_budget_rub: number;
  model_input_budget_rub: number;
  unmodeled_budget_rub: number;
  daily_budget_rub: number;
  raw_to_normalized_abs_diff_rub: number;
  normalized_to_daily_abs_diff_rub: number;
}
export interface ValidationIssue {
  code: StableCode;
  severity: "blocking" | "warning";
  display_text: string;
  scope: "upload" | "row" | "campaign" | "cell" | "model";
  recoverable: boolean;
  source_row_ids: number[];
  affected_cells: AffectedCell[];
}
export interface AffectedCell {
  campaign_id: NullableOpaqueId;
  segment: string;
  geo: string;
  channel: string;
  target: string;
}
export interface ValidationPreview {
  budget_by_channel?: BudgetByChannelPreview[];
  budget_by_geo?: BudgetByGeoPreview[];
  channel_flighting?: ChannelFlightingPreview[];
  geo_points?: GeoPointPreview[];
  checks?: ValidationPreviewCheck[];
}
export interface BudgetByChannelPreview {
  channel: string;
  total_budget_rub: number;
  max_daily_budget_rub: number;
  status?: PreviewStatus;
}
export interface PreviewStatus {
  code: "passed" | "warning" | "failed" | "unavailable";
  display_text: string;
}
export interface BudgetByGeoPreview {
  geo: string;
  total_budget_rub: number;
  max_daily_budget_rub: number;
  status?: PreviewStatus;
}
export interface ChannelFlightingPreview {
  channel: string;
  date: string;
  daily_budget_rub: number;
  status?: PreviewStatus;
}
export interface GeoPointPreview {
  geo: string;
  latitude: number;
  longitude: number;
  total_budget_rub: number;
  status?: PreviewStatus;
}
export interface ValidationPreviewCheck {
  code: StableCode;
  status: "passed" | "warning" | "failed" | "unavailable";
  display_text: string;
}
export interface DecisionJob {
  contract_name: "decision_job_v1";
  schema_version: "1.0.0";
  record_origin: RecordOrigin;
  job_id: OpaqueId;
  idempotency_key: string;
  job_type: "forecast_optimizer_report";
  created_by_actor_id: OpaqueId;
  upload_id: OpaqueId;
  validation_id: OpaqueId;
  normalized_plan: ArtifactIdentity;
  daily_flighting: ArtifactIdentity;
  workflow_config: ArtifactIdentity;
  model_selector: ModelSelector;
  policies: PolicySelection;
  sampling: SamplingProfile;
  code_reference: string;
  status: JobStatus;
  created_at_utc: string;
  queued_at_utc: string;
  started_at_utc: NullableDateTime;
  cancel_requested_at_utc: NullableDateTime;
  finished_at_utc: NullableDateTime;
  attempt_number: number;
  result_id: NullableOpaqueId;
  terminal_error_id: NullableOpaqueId;
}
export interface PolicySelection {
  optimizer_policy_id: string;
  optimizer_policy_sha256: Sha256;
  gate_policy_version: string;
  business_policy_id: string;
  business_policy_sha256: Sha256;
  business_decision_mode: string;
}
export interface SamplingProfile {
  scenario6_attempt_budget: number;
  search_posterior_draws: number;
  final_posterior_draws: number;
  search_seed: number;
  final_seed: number;
}
export interface JobEvent {
  contract_name: "job_event_v1";
  schema_version: "1.0.0";
  record_origin: RecordOrigin;
  event_id: OpaqueId;
  job_id: OpaqueId;
  sequence: number;
  attempt_number: number;
  emitted_at_utc: string;
  actor_type: "system" | "user" | "worker" | "admin";
  actor_id: NullableOpaqueId;
  from_status_code:
    ("queued" | "running" | "cancel_requested" | "succeeded" | "failed" | "cancelled" | "timed_out") | null;
  to_status: JobStatus;
  reason_code: StableCode | null;
  display_text: string;
}
export interface ProgressEvent {
  contract_name: "progress_event_v1";
  schema_version: "1.0.0";
  record_origin: RecordOrigin;
  progress_event_id: OpaqueId;
  job_id: OpaqueId;
  sequence: number;
  attempt_number: number;
  emitted_at_utc: string;
  stage: "prepare" | "forecast" | "benchmarks" | "scenario6" | "final_scoring" | "report";
  phase: StableCode;
  state: "started" | "running" | "completed";
  display_text: string;
  campaign_id: NullableOpaqueId;
  percent_complete: number | null;
  counters: ProgressCounter[];
}
export interface ProgressCounter {
  name: StableCode;
  current: number;
  total: number | null;
  unit: string;
}
export interface ApplicationError {
  contract_name: "application_error_v1";
  schema_version: "1.0.0";
  record_origin: RecordOrigin;
  error_id: OpaqueId;
  resource_type: "upload" | "validation" | "job";
  resource_id: OpaqueId;
  occurred_at_utc: string;
  component:
    "upload" | "validation" | "worker" | "forecast" | "optimizer" | "report" | "result_adapter" | "storage" | "api";
  stage:
    "upload" | "validation" | "prepare" | "forecast" | "benchmarks" | "scenario6" | "final_scoring" | "report" | null;
  code: StableCode;
  category:
    | "input_validation"
    | "model_policy"
    | "calculation"
    | "artifact_integrity"
    | "infrastructure"
    | "timeout"
    | "cancellation"
    | "internal";
  severity: "error" | "fatal";
  retryable: boolean;
  display_text: string;
  support_reference: NullableString;
  source_row_ids: number[];
  affected_cells: AffectedCell[];
}
