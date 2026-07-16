/* Generated from ../../contracts/workspace_home_v1.schema.json. Do not edit manually. */

export type OpaqueId = string;
export type NonEmptyText = string;
export type InternalPath = string;

export interface WorkspaceHomeV1 {
  contract_name: "workspace_home_v1";
  schema_version: "1.0.0";
  record_origin: "application_runtime" | "synthetic_fixture";
  summary: {
    running: number;
    queued: number;
    completed_30d: number;
    failed_30d: number;
  };
  active_calculations: ActiveCalculation[];
  recent_calculations: RecentCalculation[];
  model: ModelSummary;
  /**
   * @minItems 4
   * @maxItems 4
   */
  quick_actions: [QuickAction, QuickAction, QuickAction, QuickAction];
  warnings: Warning[];
  updated_at_utc: string;
}
export interface ActiveCalculation {
  job_id: OpaqueId;
  campaign_name: NonEmptyText;
  status: JobStatus;
  current_stage: CurrentStage | null;
  created_at_utc: string;
  progress_path: InternalPath;
  can_cancel: boolean;
  display_text: NonEmptyText;
}
export interface JobStatus {
  code: "queued" | "running" | "cancel_requested" | "succeeded" | "failed" | "cancelled" | "timed_out";
  display_text: NonEmptyText;
}
export interface CurrentStage {
  stage_id: NonEmptyText;
  title: NonEmptyText;
  status: "pending" | "active" | "completed" | "warning" | "failed" | "skipped";
  display_text: NonEmptyText;
}
export interface RecentCalculation {
  job_id: OpaqueId;
  campaign_name: NonEmptyText;
  campaign_period: Period | null;
  total_budget_rub: number | null;
  created_at_utc: string;
  completed_at_utc: string | null;
  status: JobStatus;
  result_available: boolean;
  report_available: boolean;
  result_path: InternalPath | null;
  progress_path: InternalPath;
  warnings_count: number | null;
}
export interface Period {
  start_date: string;
  end_date: string;
}
export interface ModelSummary {
  status: {
    code: "available" | "unavailable";
    display_text: NonEmptyText;
  };
  model_id: string | null;
  display_name: string | null;
  version: string | null;
  published_at_utc: string | null;
  training_period: Period | null;
  supported_scope: {
    segments: string[];
    channels: string[];
    targets: string[];
    geographies_n: number;
  } | null;
  description: NonEmptyText;
  details_path: InternalPath;
}
export interface QuickAction {
  action_id: "new_calculation" | "calculation_history" | "model_overview" | "help_catalog";
  title: NonEmptyText;
  description: NonEmptyText;
  path: InternalPath;
}
export interface Warning {
  code: NonEmptyText;
  severity: "info" | "warning" | "error";
  title: NonEmptyText;
  display_text: NonEmptyText;
  recommended_action: NonEmptyText;
  path: InternalPath | null;
}
