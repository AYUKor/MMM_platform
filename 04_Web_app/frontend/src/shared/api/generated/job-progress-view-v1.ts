/* Generated from ../../contracts/job_progress_view_v1.schema.json. Do not edit manually. */

export type OpaqueId = string;
export type NullableNonNegativeInteger = number | null;
export type StageId = "P01" | "P02" | "P03" | "P04" | "P05" | "P06" | "P07" | "P08" | "P09";
export type NullableDateTime = string | null;

export interface JobProgressViewV1 {
  contract_name: "job_progress_view_v1";
  schema_version: "1.0.0";
  record_origin: "application_runtime" | "synthetic_fixture";
  job_id: OpaqueId;
  job_status: JobStatus;
  queue: QueueSummary;
  campaign: CampaignSummary;
  current_stage_id: StageId;
  /**
   * @minItems 9
   * @maxItems 9
   */
  stages: [
    ProductStage,
    ProductStage,
    ProductStage,
    ProductStage,
    ProductStage,
    ProductStage,
    ProductStage,
    ProductStage,
    ProductStage
  ];
  scenario6: Scenario6Progress;
  report: ReportProgress;
  errors: ProgressError[];
  can_cancel: boolean;
  result_available: boolean;
  updated_at_utc: string;
}
export interface JobStatus {
  code: "queued" | "running" | "cancel_requested" | "succeeded" | "failed" | "cancelled" | "timed_out";
  display_text: string;
}
export interface QueueSummary {
  position: NullableNonNegativeInteger;
  queued_jobs_total: NullableNonNegativeInteger;
  display_text: string;
}
export interface CampaignSummary {
  campaign_id: OpaqueId;
  campaign_name: string;
  /**
   * @minItems 1
   */
  segment: [string, ...string[]];
  start_date: string;
  end_date: string;
  total_budget_rub: number;
  channels_n: number;
  geographies_n: number;
}
export interface ProductStage {
  stage_id: StageId;
  order: number;
  title: string;
  status: "pending" | "active" | "completed" | "warning" | "failed" | "skipped";
  started_at_utc: NullableDateTime;
  finished_at_utc: NullableDateTime;
  display_text: string;
  progress: StageProgress | null;
}
export interface StageProgress {
  current: number;
  total: NullableNonNegativeInteger;
  unit: string;
}
export interface Scenario6Progress {
  status: "pending" | "running" | "completed" | "unavailable" | "failed";
  attempt_budget: NullableNonNegativeInteger;
  attempts_checked: NullableNonNegativeInteger;
  safe_candidates: NullableNonNegativeInteger;
  blocked_candidates: NullableNonNegativeInteger;
  finalists_scored: NullableNonNegativeInteger;
  finalists_total: NullableNonNegativeInteger;
}
export interface ReportProgress {
  status: "pending" | "running" | "completed" | "failed" | "not_required";
  display_text: string;
  retryable: boolean;
}
export interface ProgressError {
  error_id: OpaqueId;
  stage_id: StageId;
  severity: "warning" | "error";
  blocking: boolean;
  retryable: boolean;
  display_text: string;
  recommended_action: string;
}
